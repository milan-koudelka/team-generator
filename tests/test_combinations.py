"""/avg-all, plus the optional context every endpoint accepts: which player
is shown in team A, the split played last, and the splits already played."""

import pytest

from app import MAX_AVG_PLAYERS, _random_split, _ranked_splits, app


@pytest.fixture()
def client():
    return app.test_client()


def make_players(n, mu_start=30, males=()):
    """p0..p{n-1}, strongest first, tiny sigma so ordinal ~ mu."""
    return {
        f"p{i}": {"mu": mu_start - i, "sigma": 0.001, "male": int(f"p{i}" in males)}
        for i in range(n)
    }


def split(team_a, team_b):
    return {"team_a": list(team_a), "team_b": list(team_b)}


def key(out):
    """The split in a response, whichever side is A."""
    return frozenset((frozenset(out["team_a"]), frozenset(out["team_b"])))


def k(team_a, team_b):
    return frozenset((frozenset(team_a), frozenset(team_b)))


def post(client, endpoint, players, status=200, **body):
    resp = client.post(endpoint, json={"players": players, **body})
    assert resp.status_code == status, resp.get_data(as_text=True)
    return resp.get_json()


# With p0 > p1 > p2 > p3 the splits, best first, are:
BEST = k({"p0", "p3"}, {"p1", "p2"})  # averages 28.5 and 28.5
SECOND = k({"p0", "p2"}, {"p1", "p3"})  # 29 against 28
THIRD = k({"p0", "p1"}, {"p2", "p3"})  # 29.5 against 27.5, the widest gap


class TestCombinations:
    def test_lists_every_split_once_best_first(self, client):
        out = post(client, "/avg-all", make_players(4))

        assert out["total"] == 3
        keys = [key(c) for c in out["combinations"]]
        assert keys == [BEST, SECOND, THIRD]
        diffs = [c["avg_player_ordinal_difference"] for c in out["combinations"]]
        assert diffs == sorted(diffs)
        assert diffs[0] == pytest.approx(0, abs=1e-2)

    def test_each_combination_carries_both_teams_and_the_stats(self, client):
        combo = post(client, "/avg-all", make_players(4, males=("p0",)))["combinations"][0]

        assert set(combo["team_a"]) | set(combo["team_b"]) == {"p0", "p1", "p2", "p3"}
        assert combo["team_a"]["p0"]["mu"] == 30  # player data comes back like /avg
        assert combo["total_players"] == 4
        assert combo["female_difference"] == abs(combo["team_a_females"] - combo["team_b_females"])

    def test_the_best_one_is_what_avg_returns(self, client):
        players = make_players(6)

        best = post(client, "/avg-all", players)["combinations"][0]
        avg = post(client, "/avg", players)

        assert key(best) == key(avg)
        assert best["avg_player_ordinal_difference"] == avg["avg_player_ordinal_difference"]

    def test_limit_caps_the_list_not_the_total(self, client):
        out = post(client, "/avg-all", make_players(6), limit=4)

        assert len(out["combinations"]) == 4
        assert out["total"] == 10  # C(6, 3) / 2

    def test_the_default_limit_is_twenty(self, client):
        out = post(client, "/avg-all", make_players(8))

        assert len(out["combinations"]) == 20
        assert out["total"] == 35  # C(8, 4) / 2

    def test_an_odd_count_has_the_smaller_team_first(self, client):
        out = post(client, "/avg-all", make_players(5), limit=50)

        assert out["total"] == 10
        assert all(len(c["team_a"]) + len(c["team_b"]) == 5 for c in out["combinations"])

    def test_balance_females_drops_splits_with_a_gap_of_two_or_more(self, client):
        players = make_players(4, males=("p2", "p3"))  # p0, p1 are women
        out = post(client, "/avg-all", players, balance_females=True)

        assert out["total"] == 2
        assert all(c["female_difference"] == 0 for c in out["combinations"])
        assert THIRD not in {key(c) for c in out["combinations"]}

    def test_the_order_players_are_sent_in_does_not_matter(self, client):
        players = make_players(6)
        reversed_players = dict(reversed(list(players.items())))

        one = post(client, "/avg-all", players)
        two = post(client, "/avg-all", reversed_players)

        assert [c["team_a"].keys() for c in one["combinations"]] == [
            c["team_a"].keys() for c in two["combinations"]
        ]

    def test_flags_the_splits_already_played(self, client):
        out = post(
            client,
            "/avg-all",
            make_players(4),
            played=[split({"p3", "p0"}, {"p1", "p2"})],
        )

        assert [c["already_played"] for c in out["combinations"]] == [True, False, False]

    def test_puts_the_requested_player_in_team_a_of_every_combination(self, client):
        out = post(client, "/avg-all", make_players(6), team_a_player="p4", limit=50)

        assert all("p4" in c["team_a"] for c in out["combinations"])

    def test_refuses_too_many_players(self, client):
        out = post(client, "/avg-all", make_players(MAX_AVG_PLAYERS + 1), status=400)

        assert "at most 24" in out["error"]

    @pytest.mark.parametrize("limit", [0, -1, 201, "5", 2.5, True, None])
    def test_refuses_a_bad_limit(self, client, limit):
        post(client, "/avg-all", make_players(4), status=400, limit=limit)

    def test_needs_two_players(self, client):
        post(client, "/avg-all", make_players(1), status=400)


class TestTeamA:
    @pytest.mark.parametrize("endpoint", ["/rand", "/topdown", "/avg"])
    def test_the_requested_player_is_in_team_a(self, client, endpoint):
        for player in ("p0", "p1", "p2", "p3"):
            out = post(client, endpoint, make_players(4), team_a_player=player)
            assert player in out["team_a"]

    @pytest.mark.parametrize("endpoint", ["/topdown", "/avg"])
    def test_without_a_request_the_smallest_id_is_in_team_a(self, client, endpoint):
        players = make_players(6)
        for ids in (list(players), list(reversed(list(players)))):
            out = post(client, endpoint, {pid: players[pid] for pid in ids})
            assert "p0" in out["team_a"]

    def test_a_player_who_is_not_playing_changes_nothing(self, client):
        out = post(client, "/avg", make_players(4), team_a_player="somebody-else")

        assert "p0" in out["team_a"]

    def test_the_split_played_last_keeps_its_sides_when_listed(self, client):
        # In the match played last, p1+p2 were team A and p0+p3 team B.
        played = [split({"p1", "p2"}, {"p0", "p3"})]

        out = post(
            client,
            "/avg-all",
            make_players(4),
            team_a_player="p0",  # would be in A otherwise
            played=played,
        )

        best, *others = out["combinations"]
        assert key(best) == BEST and best["already_played"] is True
        assert set(best["team_a"]) == {"p1", "p2"}
        # Any other split is oriented by team_a_player as usual.
        assert all("p0" in c["team_a"] for c in others)

    def test_only_the_last_entry_of_played_decides_the_sides(self, client):
        played = [split({"p1", "p2"}, {"p0", "p3"}), split({"p0", "p3"}, {"p1", "p2"})]

        out = post(client, "/avg-all", make_players(4), team_a_player="p1", played=played)

        assert set(out["combinations"][0]["team_a"]) == {"p0", "p3"}

    def test_the_split_played_last_keeps_its_sides_when_it_is_repeated(self, client):
        # Two players have one split only; it comes up again with its old sides.
        out = post(
            client,
            "/avg",
            make_players(2),
            team_a_player="p0",
            played=[split({"p1"}, {"p0"})],
        )

        assert out["already_played"] is True and set(out["team_a"]) == {"p1"}

    def test_a_different_split_ignores_the_one_played_last(self, client):
        out = post(
            client,
            "/avg",
            make_players(4),
            team_a_player="p3",
            played=[split({"p0", "p2"}, {"p1", "p3"})],
        )

        assert key(out) == BEST and "p3" in out["team_a"]


class TestAvoidingPlayedSplits:
    def test_avg_skips_a_played_split_and_says_so(self, client):
        out = post(client, "/avg", make_players(4), played=[split({"p0", "p3"}, {"p1", "p2"})])

        assert key(out) == SECOND
        assert out["method"] == "avg"
        assert out["repeat_avoided"] is True
        assert out["already_played"] is False
        assert out["avg_player_ordinal_difference"] > 0.5  # the stats are the new split's

    def test_avg_works_through_the_splits_in_order(self, client):
        played = []
        seen = []
        for _ in range(3):
            out = post(client, "/avg", make_players(4), played=played)
            seen.append(key(out))
            played.append(split(out["team_a"], out["team_b"]))

        assert seen == [BEST, SECOND, THIRD]

    def test_a_split_played_with_its_sides_swapped_still_counts(self, client):
        out = post(client, "/avg", make_players(4), played=[split({"p1", "p2"}, {"p0", "p3"})])

        assert key(out) == SECOND

    def test_nothing_played_reports_nothing(self, client):
        out = post(client, "/avg", make_players(4))

        assert out["already_played"] is False and out["repeat_avoided"] is False
        assert out["method"] == "avg"

    def test_when_every_split_was_played_avg_turns_random_but_not_the_last(self, client):
        played = [split(*sorted(s, key=sorted)) for s in (BEST, SECOND, THIRD)]  # THIRD is last

        seen = set()
        for _ in range(40):
            out = post(client, "/avg", make_players(4), played=played)
            assert out["method"] == "rand"
            assert out["already_played"] is True and out["repeat_avoided"] is False
            seen.add(key(out))

        assert seen == {BEST, SECOND}

    def test_which_split_is_avoided_depends_on_the_order_of_played(self, client):
        played = [split(*sorted(s, key=sorted)) for s in (THIRD, SECOND, BEST)]  # BEST is last

        seen = {key(post(client, "/avg", make_players(4), played=played)) for _ in range(40)}

        assert seen == {SECOND, THIRD}

    def test_with_only_one_split_it_is_repeated(self, client):
        out = post(client, "/avg", make_players(2), played=[split({"p0"}, {"p1"})])

        assert out["already_played"] is True
        assert {*out["team_a"], *out["team_b"]} == {"p0", "p1"}

    def test_the_random_pick_respects_balance_females(self, client):
        players = make_players(4, males=("p2", "p3"))
        played = [split({"p0", "p1"}, {"p2", "p3"}), split({"p0", "p2"}, {"p1", "p3"})]

        for _ in range(30):
            out = post(
                client,
                "/avg",
                players,
                balance_females=True,
                played=played + [split({"p0", "p3"}, {"p1", "p2"})],
            )
            assert out["female_difference"] == 0

    def test_topdown_that_lands_on_a_played_split_is_replaced(self, client):
        # topdown on p0 > p1 > p2 > p3 gives p0+p3 against p1+p2, the best one.
        plain = post(client, "/topdown", make_players(4))
        assert key(plain) == BEST and plain["method"] == "topdown"

        out = post(client, "/topdown", make_players(4), played=[split({"p0", "p3"}, {"p1", "p2"})])

        assert key(out) == SECOND
        assert out["method"] == "avg" and out["repeat_avoided"] is True
        assert "avg_player_ordinal_difference" in out

    def test_topdown_with_an_unplayed_result_is_left_alone(self, client):
        out = post(client, "/topdown", make_players(4), played=[split({"p0", "p1"}, {"p2", "p3"})])

        assert key(out) == BEST and out["method"] == "topdown"
        assert out["repeat_avoided"] is False and "avg_player_ordinal_difference" not in out

    def test_rand_draws_again_when_it_hits_a_played_split(self, client):
        played = [split(*sorted(s, key=sorted)) for s in (BEST, SECOND)]

        for _ in range(20):
            out = post(client, "/rand", make_players(4), played=played)
            assert key(out) == THIRD
            assert out["method"] == "rand" and out["repeat_avoided"] is False

    def test_rand_with_every_split_played_is_random_and_flagged(self, client):
        played = [split(*sorted(s, key=sorted)) for s in (BEST, SECOND, THIRD)]

        out = post(client, "/rand", make_players(4), played=played)

        assert out["already_played"] is True and out["method"] == "rand"

    def test_too_many_players_to_enumerate_leaves_a_played_topdown_as_it_is(self, client):
        players = make_players(MAX_AVG_PLAYERS + 2)
        plain = post(client, "/topdown", players)
        played = [split(plain["team_a"], plain["team_b"])]

        out = post(client, "/topdown", players, played=played)

        assert key(out) == key(plain)
        assert out["already_played"] is True and out["method"] == "topdown"


class TestValidation:
    @pytest.mark.parametrize("endpoint", ["/rand", "/topdown", "/avg", "/avg-all"])
    @pytest.mark.parametrize(
        "extra",
        [
            {"team_a_player": 5},
            {"played": [{"team_a": ["p0"]}]},
            {"played": [{"team_a": ["p0"], "team_b": [1]}]},
            {"played": "nope"},
            {"played": ["nope"]},
            {"played": [{"team_a": "p0", "team_b": []}]},
        ],
    )
    def test_refuses_malformed_context(self, client, endpoint, extra):
        out = post(client, endpoint, make_players(4), status=400, **extra)

        assert "error" in out

    def test_a_null_team_a_player_is_fine(self, client):
        post(client, "/avg", make_players(4), team_a_player=None)

    def test_played_splits_with_unknown_players_are_simply_ignored(self, client):
        out = post(client, "/avg", make_players(4), played=[split({"x"}, {"y"})])

        assert key(out) == BEST and out["repeat_avoided"] is False


class TestEngine:
    def test_ranked_splits_are_unique_and_sorted_by_difference(self):
        players = {k_: {"mu": 25 + i, "sigma": 1.0, "male": 1} for i, k_ in enumerate("abcdef")}

        ranked, total = _ranked_splits(players, False, limit=100)

        assert total == 10 and len(ranked) == 10
        assert len({k(a, b) for a, b in ranked}) == 10

    def test_ties_come_out_stable_unless_shuffled(self):
        players = {c: {"mu": 25.0, "sigma": 5.0, "male": 1} for c in "abcdefgh"}

        first = _ranked_splits(players, False, limit=5)[0]
        again = _ranked_splits(players, False, limit=5)[0]
        assert first == again

        seen = {
            tuple(_ranked_splits(players, False, 1, shuffle_ties=True)[0][0][0]) for _ in range(20)
        }
        assert len(seen) > 1

    def test_a_random_split_avoids_the_given_one_but_covers_the_rest(self):
        players = {c: {"mu": 25.0, "sigma": 5.0, "male": 1} for c in "abcd"}

        seen = {k(*_random_split(players, False, avoid={k("ab", "cd")})) for _ in range(60)}

        assert seen == {k("ac", "bd"), k("ad", "bc")}

    def test_a_random_split_may_return_the_avoided_one_if_it_is_the_only_one(self):
        players = {c: {"mu": 25.0, "sigma": 5.0, "male": 1} for c in "ab"}

        assert k(*_random_split(players, False, avoid={k("a", "b")})) == k("a", "b")
