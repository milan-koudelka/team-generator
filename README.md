<h1>Team generator</h1>
<p>This REST API allows you to split list of players to two teams by different algorithms. The app is written as Python REST API based on Flask.</p>

<p>To use the app you need to start a Docker container.</p>
<pre>docker run -d -p 5000:5000 docker.io/koudisek/teamgenerator</pre>

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

<h4>Example requests</h4>
<pre>
curl http://127.0.0.1:5000/rand -X POST -H 'Content-Type: application/json' --data-b "$(cat data3.json)" | jq
curl http://127.0.0.1:5000/topdown -X POST -H 'Content-Type: application/json' --data-b "$(cat data12.json)" | jq
curl http://127.0.0.1:5000/avg -X POST -H 'Content-Type: application/json' --data-b "$(cat data12.json)" | jq
</pre>

<h4>Example result</h4>
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
