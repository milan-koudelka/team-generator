# A Python program to print all 
# combinations of given length
from itertools import combinations
from flask import Flask, request, jsonify
import json
import random

app = Flask(__name__)

@app.route('/')
def landingpage():
    return '''
<h1>Team generator</h1>
<p>This REST API allows you to split list of players to two teams by different algorithms. The app is written as Python REST API based on Flask.</p>

<h2>REST API</h2>
Send the request with the list of players to the REST API and retrieve the JSON with players split into two teams.

<h3>Create a JSON file</h3>
<pre>
{
  "players":
     {
       "1":
           {
               "skill":25,
               "sigma":8.333,
               "male":0
           },
       "2":
           {
               "skill":20,
               "sigma":8.333,
               "male":0
           },
       "3":
           {
               "skill":10,
               "sigma":8.333,
               "male":0
           }
     }
}
</pre>

<h3>Endpoints</h3>
You can use several endpoints

<ul>
<li>rand - split players to the teams randomly</li>
<li>topdown - from the first half of the players the strongest player goes to team A, the second strongest player goes to team B. From the second half of the players the weakest player goes to team A, the second weakest player goes to team B</li>
<li>avg - split the players to two teams based on average player skill in each team, but keep count of females equal in both teams</li>
</ul>

<h4>Example requests<h4>
<pre>
curl http://127.0.0.1:5000/rand -X POST -H 'Content-Type: application/json' --data-b "$(cat data3.json)" | jq
curl http://127.0.0.1:5000/topdown -X POST -H 'Content-Type: application/json' --data-b "$(cat data12.json)" | jq
curl http://127.0.0.1:5000/avg -X POST -H 'Content-Type: application/json' --data-b "$(cat data12.json)" | jq
</pre>

<h4>Example result<h4>
<pre>
{
  "team_a": {
    "1": {
      "skill": 25,
      "sigma": 8.333,
      "male": 0
    }
  },
  "team_b": {
    "2": {
      "skill": 20,
      "sigma": 8.333,
      "male": 0
    },
    "3": {
      "skill": 10,
      "sigma": 8.333,
      "male": 0
    }
  }
}
</pre>
'''

@app.post("/rand")
# split the players to two random teams
def rand():
    # prepare dictionary for two teams
    output = {'team_a': {}, 'team_b': {}}
    if request.is_json:
        # load the json data
        data = request.get_json()
        # until any players are left in the original dictionary choose one random player and put him to one of the teams
        while len(data["players"]) > 0:
          # choose random player
          player = random.choice(list(data["players"].keys())) # nosemgrep - ignore B311 - Use of Insufficiently Random Values
          # assign every odd player to team A
          if len(data["players"]) % 2 == 0:
            output['team_a'][player] = data["players"][player]
          # assign every even player to team B
          if len(data["players"]) % 2 == 1:
            output['team_b'][player] = data["players"][player]
          # remove the player from the original dictionary
          data["players"].pop(player)
        # return output json
        return json.dumps(output), 201
    return {"error": "Request must be JSON"}, 415

@app.post("/topdown")
# split the players to two teams
# from the first half of the players the strongest player goes to team A, the second strongest player goes to team B
# from the second half of the players the weakest player goes to team A, the second weakest player goes to team B
def topdown():
    # prepare dictionary for two teams
    output = {'team_a': {}, 'team_b': {}}
    if request.is_json:
        # load the json data
        data = request.get_json()
        all_players = data["players"]
        # sort all players by their skill value
        all_players_sorted = dict(sorted(all_players.items(), key=lambda item: item[1]["skill"], reverse = True))
        # split the players to two halves
        firsthalfofplayers = dict(list(all_players_sorted.items())[len(all_players)//2:])
        secondhalfofplayers = dict(list(all_players_sorted.items())[:len(all_players)//2])
        # merge the dictionaries
        finalplayers_sorted = {}
        # first half is sorted from the strongest to the weakest player
        finalplayers_sorted.update(firsthalfofplayers)
        # second half is sorted from the weakest to the strongest player
        finalplayers_sorted.update(dict(reversed(secondhalfofplayers.items())))
        n = 0
        for player in set(finalplayers_sorted.keys()):
            n = n + 1
            if n % 2 == 0:
              # every odd player goes to team A
              output['team_a'][player] = all_players[player]
            else:
              # every even player goes to team B
              output['team_b'][player] = all_players[player]
        # return output json
        return json.dumps(output), 201
    return {"error": "Request must be JSON"}, 415

@app.post("/avg")
# split the players to two teams based on average player skill in each team, but keep count of females equal in both teams
def avg():
    # prepare dictionary for two teams
    output = {'team_a': {}, 'team_b': {}}
    if request.is_json:
        closest_difference = None
        # load the json data
        data = request.get_json()
        all_players_set = set(data["players"].keys())

        # create all combinations for team A
        for team_a in combinations(data["players"].keys(), len(all_players_set) // 2):
            team_a_set = set(team_a)
            # the remaining players are team B
            team_b_set = all_players_set - team_a_set

            # sum player skills in each team
            team_a_total = sum([data["players"][x]["skill"] for x in team_a_set])
            team_b_total = sum([data["players"][x]["skill"] for x in team_b_set])
            # count difference between avg player skill in each team
            avg_player_skill_difference = abs(team_a_total / len(team_a_set) - team_b_total / len(team_b_set))

            # count females in each team
            team_a_female_total = sum([(1-data["players"][x]["male"]) for x in team_a_set])
            team_b_female_total = sum([(1-data["players"][x]["male"]) for x in team_b_set])
            # count a difference of females in each team
            female_difference = abs(team_a_female_total - team_b_female_total)

            # if current teams are better balanced than any previous choice or if this is the first choice and the count of females is balanced, pick them as best choice
            if (closest_difference == None or avg_player_skill_difference < closest_difference) and female_difference < 2:
                closest_difference = avg_player_skill_difference
                best_team_a = team_a_set     
                best_team_b = team_b_set  

        for player in best_team_a:
            output['team_a'][player] = data["players"][player]
        output['team_a_players'] = len(best_team_a)
        best_team_a_total = sum([data["players"][x]["skill"] for x in best_team_a])
        output['team_a_skill'] = sum([data["players"][x]["skill"] for x in best_team_a])
        output['avg_player_team_a_skill'] = best_team_a_total / len(best_team_a)

        for player in best_team_b:
            output['team_b'][player] = data["players"][player]
        output['team_b_players'] = len(best_team_b)
        best_team_b_total = sum([data["players"][x]["skill"] for x in best_team_b])
        output['team_b_skill'] = best_team_b_total
        output['avg_player_team_b_skill'] = best_team_b_total / len(best_team_b)

        avg_player_skill_difference = abs(best_team_a_total / len(best_team_a) - best_team_b_total / len(best_team_b))
        output['avg_player_skill_difference'] = avg_player_skill_difference

        # count females in each team
        team_a_female_total = sum([(1-data["players"][x]["male"]) for x in best_team_a])
        team_b_female_total = sum([(1-data["players"][x]["male"]) for x in best_team_b])
        output['team_a_females'] = team_a_female_total
        output['team_b_females'] = team_b_female_total
        # count males in each team
        team_a_male_total = sum([data["players"][x]["male"] for x in best_team_a])
        team_b_male_total = sum([data["players"][x]["male"] for x in best_team_b])
        output['team_a_males'] = team_a_male_total
        output['team_b_males'] = team_b_male_total

        # calculate difference in count of females in each team
        female_difference = abs(team_a_female_total - team_b_female_total)
        output['female_difference'] = female_difference
        # count of all players
        output['total_players'] = len(data["players"])
        # output json data
        return json.dumps(output), 201
    return {"error": "Request must be JSON"}, 415

if __name__ == "__main__":
    app.run(debug=False)
