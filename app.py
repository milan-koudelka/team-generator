# A Python program to split a list of players into two balanced teams.
import random
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
</ul>

<h4>Example requests</h4>
<pre>
curl --json "$(cat data3.json)" http://127.0.0.1:5000/rand | jq
curl --json "$(cat data12.json)" http://127.0.0.1:5000/topdown | jq
curl --json "$(cat data12.json)" http://127.0.0.1:5000/avg | jq
</pre>
"""


@app.post("/rand")
# split the players into two random teams
def rand():
    players, balance_females = _parse_request()

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

    return jsonify(_teams_dict(a, b, players))


@app.post("/topdown")
# snake draft by ordinal: from the first half the strongest goes to team A, the
# next to team B; from the second half the weakest goes to team A, next to B.
def topdown():
    players, balance_females = _parse_request()

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

    return jsonify(_teams_dict(a, b, players))


@app.post("/avg")
# split into two teams balanced by average OpenSkill ordinal
def avg():
    players, balance_females = _parse_request()
    if len(players) > MAX_AVG_PLAYERS:
        raise ValidationError(
            f"'avg' supports at most {MAX_AVG_PLAYERS} players ({len(players)} given)"
        )
    all_ids = list(players.keys())
    all_players_set = set(all_ids)
    ordinal = {pid: _ordinal(p) for pid, p in players.items()}
    team_size = len(all_ids) // 2

    # With an even player count every split would be enumerated twice (A/B and
    # B/A swapped) — pinning one player into team A halves the work.
    if len(all_ids) % 2 == 0:
        pinned, rest = all_ids[0], all_ids[1:]
        candidates = ((pinned,) + tail for tail in combinations(rest, team_size - 1))
    else:
        candidates = combinations(all_ids, team_size)

    best_team_a = None
    best_team_b = None
    closest_difference = None
    # try every way to pick team A; the rest is team B
    for team_a in candidates:
        team_a_set = set(team_a)
        team_b_set = all_players_set - team_a_set

        if balance_females:
            team_a_females = sum((1 - players[x]["male"]) for x in team_a_set)
            team_b_females = sum((1 - players[x]["male"]) for x in team_b_set)
            # one team may have at most one female more (odd female counts);
            # with zero or one female this filters nothing
            if abs(team_a_females - team_b_females) >= 2:
                continue

        team_a_total = sum(ordinal[x] for x in team_a_set)
        team_b_total = sum(ordinal[x] for x in team_b_set)
        avg_difference = abs(team_a_total / len(team_a_set) - team_b_total / len(team_b_set))
        if closest_difference is None or avg_difference < closest_difference:
            closest_difference = avg_difference
            best_team_a = team_a_set
            best_team_b = team_b_set

    if best_team_a is None:
        # unreachable with validated input (a female-balanced split always
        # exists), kept as a guard against future filters
        raise ValidationError("No split satisfies the requested constraints")

    stats_a = _team_stats(best_team_a, players, ordinal)
    stats_b = _team_stats(best_team_b, players, ordinal)
    output = _teams_dict(best_team_a, best_team_b, players)
    output.update(
        {
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
            "total_players": len(players),
        }
    )
    return jsonify(output)


if __name__ == "__main__":
    app.run(debug=False)
