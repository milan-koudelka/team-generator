# A Python program to split a list of players into two balanced teams.
import random
from dataclasses import dataclass
from functools import cached_property
from heapq import nsmallest
from itertools import combinations

from flask import Flask, jsonify, request
from openskill.models import PlackettLuce

app = Flask(__name__)

# Reject oversized request bodies outright (Flask answers 413).
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024

# /avg tries every combination — C(n, n/2) grows so fast that 24 players
# (~2.7M splits, a few seconds) is a sane ceiling; 30+ would run for minutes
# and wedge the worker.
MAX_AVG_PLAYERS = 24

# /rand draws again this many times before falling back when it lands on a
# split that was already played.
RAND_REDRAWS = 30

# /avg-all returns the best `limit` splits.
DEFAULT_COMBINATIONS_LIMIT = 20
MAX_COMBINATIONS_LIMIT = 200

# --- Skill model ------------------------------------------------------------
# We use OpenSkill (PlackettLuce). A player carries mu and sigma (the receiving
# system persists both); balancing and ranking use the OpenSkill *ordinal*
# (mu - 3*sigma), which is what we expose to users instead of raw mu.
# OpenSkill defaults match the numbers the service has always used and are the
# starting rating for all players and every newly registered player.
MODEL = PlackettLuce()
_DEFAULT_RATING = MODEL.rating()
DEFAULT_MU = _DEFAULT_RATING.mu  # 25.0
DEFAULT_SIGMA = _DEFAULT_RATING.sigma  # 8.333333333333334


class ValidationError(Exception):
    """Invalid client input; rendered as a 400 JSON error."""


@app.errorhandler(ValidationError)
def _validation_error(exc):
    return jsonify({"error": str(exc)}), 400


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _parse_request():
    """Validate the request and return (players, balance_females).

    Fills in default mu/sigma/male for players that omit them and normalises
    male to 0/1. Raises ValidationError (-> 400) on any malformed input, so
    the endpoints can assume clean data.
    """
    if not request.is_json:
        raise ValidationError("Request must be JSON")
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError("Request body must be a JSON object")

    balance_females = data.get("balance_females", False)
    if not isinstance(balance_females, bool):
        raise ValidationError("'balance_females' must be a boolean")

    players = data.get("players")
    if not isinstance(players, dict) or len(players) < 2:
        raise ValidationError("'players' must be an object with at least 2 players")

    for pid, player in players.items():
        if not isinstance(player, dict):
            raise ValidationError(f"Player '{pid}' must be an object")
        player.setdefault("mu", DEFAULT_MU)
        player.setdefault("sigma", DEFAULT_SIGMA)
        player.setdefault("male", 0)
        if not _is_number(player["mu"]):
            raise ValidationError(f"Player '{pid}': 'mu' must be a number")
        if not _is_number(player["sigma"]) or player["sigma"] <= 0:
            raise ValidationError(f"Player '{pid}': 'sigma' must be a positive number")
        if not isinstance(player["male"], (int, bool)) or player["male"] not in (0, 1):
            raise ValidationError(f"Player '{pid}': 'male' must be 0 or 1")
        player["male"] = int(player["male"])

    return players, balance_females


@dataclass(frozen=True)
class Hints:
    """Optional context a caller can send with any request.

    facilitator:   the person running the draw. If they are playing they are
                   shown in team A, so they always know which side is theirs.
    played:        splits already played, oldest first; the draw avoids them
                   while another exists. The last one is the split played
                   last: if the result is that split it keeps its sides, so a
                   continued match never swaps teams, and once every split has
                   been played the random pick avoids it. The service is
                   stateless, the caller owns the history.
    """

    facilitator: str | None = None
    played: tuple[tuple[frozenset, frozenset], ...] = ()

    @cached_property
    def played_keys(self):
        return frozenset(_split_key(team_a, team_b) for team_a, team_b in self.played)

    @property
    def last_split(self):
        return self.played[-1] if self.played else None


def _parse_split(value, name):
    """{"team_a": [ids], "team_b": [ids]} -> (frozenset, frozenset)."""
    if not isinstance(value, dict):
        raise ValidationError(f"'{name}' must be an object with 'team_a' and 'team_b'")
    sides = []
    for side in ("team_a", "team_b"):
        ids = value.get(side)
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            raise ValidationError(f"'{name}.{side}' must be a list of player ids")
        sides.append(frozenset(ids))
    return tuple(sides)


def _split_key(team_a, team_b):
    """Identity of a split regardless of which side is called A."""
    return frozenset((frozenset(team_a), frozenset(team_b)))


def _parse_hints():
    """Validate the optional facilitator / played fields of the (already
    validated) request body."""
    data = request.get_json(silent=True)

    facilitator = data.get("facilitator")
    if facilitator is not None and not isinstance(facilitator, str):
        raise ValidationError("'facilitator' must be a player id")

    played = data.get("played", [])
    if not isinstance(played, list):
        raise ValidationError("'played' must be a list of splits")
    return Hints(
        facilitator=facilitator,
        played=tuple(_parse_split(item, "played[]") for item in played),
    )


def _orient(team_a, team_b, hints):
    """Decide which side is shown as team A, so the labels never jump around:

    1. the same split as the one played last (the end of hints.played) keeps
       that split's sides;
    2. otherwise the side with the facilitator is A;
    3. otherwise the side holding the smallest player id is A, so the result
       does not depend on the order players were sent in.
    """
    a_set, b_set = set(team_a), set(team_b)
    if hints.last_split is not None:
        last_a, last_b = hints.last_split
        if a_set == last_a and b_set == last_b:
            return list(team_a), list(team_b)
        if a_set == last_b and b_set == last_a:
            return list(team_b), list(team_a)
    if hints.facilitator in b_set:
        return list(team_b), list(team_a)
    if hints.facilitator in a_set:
        return list(team_a), list(team_b)
    if min(a_set | b_set) in a_set:
        return list(team_a), list(team_b)
    return list(team_b), list(team_a)


def _ordinal(player):
    """OpenSkill single-number skill estimate (mu - 3*sigma) used for ranking
    and balancing. Conservative: high uncertainty lowers the estimate."""
    return MODEL.rating(mu=player["mu"], sigma=player["sigma"]).ordinal()


def _split_by_gender(players):
    females = [pid for pid, p in players.items() if not p["male"]]
    males = [pid for pid, p in players.items() if p["male"]]
    return females, males


def _assign_to_smaller(ids, a, b, tie_random):
    """Assign each id to the currently smaller team (keeps team sizes, and —
    when a single gender is fed as one block — female counts, balanced)."""
    for pid in ids:
        if len(a) < len(b):
            a.append(pid)
        elif len(b) < len(a):
            b.append(pid)
        elif tie_random:
            # nosemgrep - ignore B311 - Use of Insufficiently Random Values
            (a if random.random() < 0.5 else b).append(pid)
        else:
            a.append(pid)


def _assign_balanced(ids_desc, a, b, players):
    """Assign ids (strongest first) so that sizes stay balanced and, on a size
    tie, the currently weaker team picks first. Equivalent to a fair snake
    draft: neither team systematically gets the better player of each pair."""
    for pid in ids_desc:
        if len(a) < len(b):
            a.append(pid)
        elif len(b) < len(a):
            b.append(pid)
        else:
            total_a = sum(_ordinal(players[x]) for x in a)
            total_b = sum(_ordinal(players[x]) for x in b)
            (b if total_b < total_a else a).append(pid)


def _teams_dict(a_ids, b_ids, players):
    return {
        "team_a": {pid: players[pid] for pid in a_ids},
        "team_b": {pid: players[pid] for pid in b_ids},
    }


def _team_stats(team_ids, players, ordinal):
    total = sum(ordinal[x] for x in team_ids)
    return {
        "players": len(team_ids),
        "ordinal": total,
        "avg_ordinal": total / len(team_ids),
        "females": sum(1 - players[x]["male"] for x in team_ids),
        "males": sum(players[x]["male"] for x in team_ids),
    }


def _split_stats(team_a, team_b, players):
    """Figures describing a split, the same ones /avg reports."""
    ordinal = {pid: _ordinal(players[pid]) for pid in [*team_a, *team_b]}
    stats_a = _team_stats(team_a, players, ordinal)
    stats_b = _team_stats(team_b, players, ordinal)
    return {
        "team_a_players": stats_a["players"],
        "team_a_ordinal": stats_a["ordinal"],
        "avg_player_team_a_ordinal": stats_a["avg_ordinal"],
        "team_b_players": stats_b["players"],
        "team_b_ordinal": stats_b["ordinal"],
        "avg_player_team_b_ordinal": stats_b["avg_ordinal"],
        "avg_player_ordinal_difference": abs(stats_a["avg_ordinal"] - stats_b["avg_ordinal"]),
        "team_a_females": stats_a["females"],
        "team_b_females": stats_b["females"],
        "team_a_males": stats_a["males"],
        "team_b_males": stats_b["males"],
        "female_difference": abs(stats_a["females"] - stats_b["females"]),
        "total_players": len(team_a) + len(team_b),
    }


def _candidate_teams(n):
    """Every split of players 0..n-1 exactly once, as the index tuple of team A
    (the smaller side; with an even count the side holding player 0, since
    otherwise each split would be seen twice, as A/B and as B/A)."""
    size = n // 2
    if n % 2 == 0:
        return ((0,) + tail for tail in combinations(range(1, n), size - 1))
    return combinations(range(n), size)


def _check_enumerable(players):
    if len(players) > MAX_AVG_PLAYERS:
        raise ValidationError(
            f"This needs every combination, so it supports at most {MAX_AVG_PLAYERS} players "
            f"({len(players)} given)"
        )


def _ranked_splits(players, balance_females, limit, shuffle_ties=False):
    """The `limit` most balanced splits, smallest difference of the teams'
    average ordinal first, as [(team_a_ids, team_b_ids)], plus how many splits
    there are in all.

    With balance_females a split whose female counts differ by 2 or more is
    not a candidate. Equal differences are common (new groups rate everyone
    the same): they come out in a stable order, or random with shuffle_ties.
    Players are taken in sorted id order, so the order they were sent in never
    matters."""
    ids = sorted(players)
    n = len(ids)
    ordinal = [_ordinal(players[pid]) for pid in ids]
    females = [1 - players[pid]["male"] for pid in ids]
    total_ordinal, total_females = sum(ordinal), sum(females)
    size = n // 2
    rng = random.Random() if shuffle_ties else None  # nosemgrep - ignore B311
    seen = 0

    def scored():
        nonlocal seen
        for team_a in _candidate_teams(n):
            if balance_females:
                a_females = sum(females[i] for i in team_a)
                # one team may have at most one female more (odd female counts);
                # with zero or one female this filters nothing
                if abs(a_females - (total_females - a_females)) >= 2:
                    continue
            a_total = sum(ordinal[i] for i in team_a)
            difference = abs(a_total / size - (total_ordinal - a_total) / (n - size))
            seen += 1
            yield (round(difference, 9), rng.random() if rng else seen, team_a)

    ranked = []
    for _, _, team_a in nsmallest(limit, scored()):
        in_a = set(team_a)
        ranked.append(([ids[i] for i in team_a], [ids[i] for i in range(n) if i not in in_a]))
    return ranked, seen


def _random_split(players, balance_females, avoid=frozenset()):
    """One split chosen uniformly at random from all that are allowed. Splits
    in `avoid` are skipped unless nothing else exists."""
    ids = sorted(players)
    n = len(ids)
    index = {pid: i for i, pid in enumerate(ids)}
    females = [1 - players[pid]["male"] for pid in ids]
    total_females = sum(females)
    # A candidate (sorted index tuple) is one side of a split, so a split to
    # avoid is recognised by either of its sides.
    avoided_sides = {
        tuple(sorted(index[pid] for pid in side))
        for key in avoid
        for side in key
        if all(pid in index for pid in side)
    }

    for skip in (avoided_sides, set()):
        chosen, seen = None, 0
        for team_a in _candidate_teams(n):
            if team_a in skip:
                continue
            if balance_females:
                a_females = sum(females[i] for i in team_a)
                if abs(a_females - (total_females - a_females)) >= 2:
                    continue
            seen += 1
            # reservoir sampling: every candidate ends up chosen with equal odds
            if random.random() * seen < 1:  # nosemgrep - ignore B311
                chosen = team_a
        if chosen is not None:
            in_a = set(chosen)
            return [ids[i] for i in chosen], [ids[i] for i in range(n) if i not in in_a]
    raise ValidationError("No split satisfies the requested constraints")


def _best_unplayed(players, balance_females, hints, shuffle_ties):
    """(team_a, team_b, exhausted, skipped): the most balanced split not played
    yet, where `skipped` says it is not the most balanced one overall because
    that was played. When every split has been played: a random one (not the
    one played last, if any other) with exhausted true. Only for at most
    MAX_AVG_PLAYERS."""
    ranked, _ = _ranked_splits(
        players, balance_females, limit=len(hints.played_keys) + 1, shuffle_ties=shuffle_ties
    )
    for position, (team_a, team_b) in enumerate(ranked):
        if _split_key(team_a, team_b) not in hints.played_keys:
            return team_a, team_b, False, position > 0
    avoid = {_split_key(*hints.last_split)} if hints.last_split else set()
    team_a, team_b = _random_split(players, balance_females, avoid)
    return team_a, team_b, True, False


def _respond(method, team_a, team_b, players, hints, *, with_stats, repeat_avoided=False):
    """The response of a draw: the teams, which method produced them, and what
    happened about splits already played."""
    team_a, team_b = _orient(team_a, team_b, hints)
    output = _teams_dict(team_a, team_b, players)
    output["method"] = method
    output["already_played"] = _split_key(team_a, team_b) in hints.played_keys
    output["repeat_avoided"] = repeat_avoided
    if with_stats:
        output.update(_split_stats(team_a, team_b, players))
    return jsonify(output)


def _avoid_played(method, team_a, team_b, players, balance_females, hints, redraw=None):
    """Replace a draw that landed on an already played split, if possible.

    /rand first draws again (`redraw` gives another split); anything still
    played is replaced by the most balanced unplayed split, which is reported
    as method 'avg'. If every split was played, a random one is chosen and
    reported as 'rand' with already_played true. Past MAX_AVG_PLAYERS the
    splits cannot be enumerated, so the played one is returned as it is."""
    if _split_key(team_a, team_b) not in hints.played_keys:
        return _respond(method, team_a, team_b, players, hints, with_stats=method == "avg")
    if redraw:
        for _ in range(RAND_REDRAWS):
            team_a, team_b = redraw()
            if _split_key(team_a, team_b) not in hints.played_keys:
                return _respond(method, team_a, team_b, players, hints, with_stats=False)
    if len(players) > MAX_AVG_PLAYERS:
        return _respond(method, team_a, team_b, players, hints, with_stats=False)
    team_a, team_b, exhausted, _ = _best_unplayed(
        players, balance_females, hints, shuffle_ties=True
    )
    return _respond(
        "rand" if exhausted else "avg",
        team_a,
        team_b,
        players,
        hints,
        with_stats=True,
        repeat_avoided=not exhausted,
    )


@app.route("/")
def landingpage():
    return f"""
<h1>Team generator</h1>
<p>This REST API splits a list of players into two teams using different
algorithms. Written as a Python REST API on Flask. Player skill is modelled
with OpenSkill (PlackettLuce); teams are balanced and ranked by the OpenSkill
ordinal (mu - 3*sigma).</p>

<h2>REST API</h2>
Send a request with the list of players (at least 2) and get back the two
teams as JSON. Each player carries <code>mu</code> and <code>sigma</code>
(both returned so the caller can persist them). Both are optional — omitted
players get the OpenSkill defaults (mu={DEFAULT_MU}, sigma={DEFAULT_SIGMA:.4f}).
Invalid input is answered with HTTP 400 and an <code>error</code> message.

<p>Set <code>"balance_females": true</code> at the top level to keep the number
of females equal in both teams (with an odd number of females one team has one
more; with zero females it changes nothing). It works with every endpoint and
is disabled by default.</p>

<h3>Create a JSON file</h3>
<pre>
{{
  "balance_females": false,
  "players":
     {{
       "1": {{ "mu": 25, "sigma": 8.333, "male": 0 }},
       "2": {{ "mu": 20, "sigma": 8.333, "male": 0 }},
       "3": {{ "male": 0 }}
     }}
}}
</pre>

<h3>Endpoints</h3>
<ul>
<li>rand - split players into teams randomly</li>
<li>topdown - snake draft by OpenSkill ordinal</li>
<li>avg - balance the two teams by average OpenSkill ordinal (max {MAX_AVG_PLAYERS} players)</li>
<li>avg-all - like avg, but lists every way to split the players, most balanced
first, the best <code>limit</code> of them (default {DEFAULT_COMBINATIONS_LIMIT},
max {MAX_COMBINATIONS_LIMIT}; max {MAX_AVG_PLAYERS} players)</li>
</ul>

<h3>Optional context</h3>
<p>Every endpoint also accepts <code>facilitator</code> (the person running the
draw, who is in team A if playing) and <code>played</code> (splits already
played, oldest first: a draw avoids them while another exists, the last one
keeps its sides, and once all are played it picks randomly, but not the last). Responses of the draw endpoints
say what happened in <code>method</code>, <code>already_played</code> and
<code>repeat_avoided</code>. See the README for the details.</p>

<h4>Example requests</h4>
<pre>
curl --json "$(cat data3.json)" http://127.0.0.1:5000/rand | jq
curl --json "$(cat data12.json)" http://127.0.0.1:5000/topdown | jq
curl --json "$(cat data12.json)" http://127.0.0.1:5000/avg | jq
curl --json "$(cat data12.json)" http://127.0.0.1:5000/avg-all | jq
</pre>
"""


def _random_teams(players, balance_females):
    a, b = [], []
    if balance_females:
        # deal each gender as a block so female (and total) counts stay balanced
        females, males = _split_by_gender(players)
        random.shuffle(females)  # nosemgrep - ignore B311
        random.shuffle(males)  # nosemgrep - ignore B311
        _assign_to_smaller(females, a, b, tie_random=True)
        _assign_to_smaller(males, a, b, tie_random=True)
    else:
        ids = list(players.keys())
        random.shuffle(ids)  # nosemgrep - ignore B311
        _assign_to_smaller(ids, a, b, tie_random=True)
    return a, b


@app.post("/rand")
# split the players into two random teams
def rand():
    players, balance_females = _parse_request()
    hints = _parse_hints()

    a, b = _random_teams(players, balance_females)
    return _avoid_played(
        "rand",
        a,
        b,
        players,
        balance_females,
        hints,
        redraw=lambda: _random_teams(players, balance_females),
    )


@app.post("/topdown")
# snake draft by ordinal: from the first half the strongest goes to team A, the
# next to team B; from the second half the weakest goes to team A, next to B.
def topdown():
    players, balance_females = _parse_request()
    hints = _parse_hints()

    a, b = [], []
    if balance_females:
        # draft each gender separately (strongest first) so female counts stay
        # balanced; on a size tie the weaker team picks, so neither team
        # systematically gets the better player of each pair
        females, males = _split_by_gender(players)
        females.sort(key=lambda pid: _ordinal(players[pid]), reverse=True)
        males.sort(key=lambda pid: _ordinal(players[pid]), reverse=True)
        _assign_balanced(females, a, b, players)
        _assign_balanced(males, a, b, players)
    else:
        sorted_desc = sorted(players.keys(), key=lambda pid: _ordinal(players[pid]), reverse=True)
        first_half = sorted_desc[len(sorted_desc) // 2 :]  # weaker half
        second_half = sorted_desc[: len(sorted_desc) // 2]  # stronger half
        final = list(first_half) + list(reversed(second_half))
        for n, pid in enumerate(final, start=1):
            if n % 2 == 0:
                a.append(pid)
            else:
                b.append(pid)

    return _avoid_played("topdown", a, b, players, balance_females, hints)


@app.post("/avg")
# split into two teams balanced by average OpenSkill ordinal
def avg():
    players, balance_females = _parse_request()
    hints = _parse_hints()
    _check_enumerable(players)

    # Best split first; with a played history, the best one not played yet.
    team_a, team_b, exhausted, skipped = _best_unplayed(
        players, balance_females, hints, shuffle_ties=False
    )
    return _respond(
        "rand" if exhausted else "avg",
        team_a,
        team_b,
        players,
        hints,
        with_stats=True,
        repeat_avoided=skipped,
    )


@app.post("/avg-all")
# like /avg, but every way to split the players, most balanced first
def avg_all():
    players, balance_females = _parse_request()
    hints = _parse_hints()
    _check_enumerable(players)

    limit = request.get_json(silent=True).get("limit", DEFAULT_COMBINATIONS_LIMIT)
    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or not (1 <= limit <= MAX_COMBINATIONS_LIMIT)
    ):
        raise ValidationError(f"'limit' must be an integer from 1 to {MAX_COMBINATIONS_LIMIT}")

    ranked, total = _ranked_splits(players, balance_females, limit)
    combos = []
    for team_a, team_b in ranked:
        team_a, team_b = _orient(team_a, team_b, hints)
        combos.append(
            {
                **_teams_dict(team_a, team_b, players),
                **_split_stats(team_a, team_b, players),
                "already_played": _split_key(team_a, team_b) in hints.played_keys,
            }
        )
    return jsonify({"total": total, "combinations": combos})


if __name__ == "__main__":
    app.run(debug=False)
