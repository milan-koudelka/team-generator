<h1>Team generator</h1>
<p>This REST API splits a list of players into two teams using different
algorithms. Written as a Python REST API on Flask.</p>

<p>Player skill is modelled with <a href="https://openskill.me">OpenSkill</a>
(PlackettLuce). Each player carries <code>mu</code> and <code>sigma</code>
(both are returned so the caller can persist them), but teams are balanced and
ranked by the OpenSkill <em>ordinal</em> — a conservative single-number
estimate, <code>mu - 3*sigma</code> — which is what we surface instead of raw
<code>mu</code>.</p>

<p>To use the app you need to start a Docker container.</p>
<pre>docker run -d -p 5000:5000 docker.io/koudisek/teamgenerator</pre>

<h2>REST API</h2>
Send a request with the list of players and get back the two teams as JSON.

<h3>Skill model &amp; defaults</h3>
<p><code>mu</code> and <code>sigma</code> (uncertainty) are optional. Any player
without them gets the OpenSkill defaults — this is what all players have at the
start, and what every newly registered player gets:</p>
<ul>
<li><code>mu</code> = <strong>25.0</strong></li>
<li><code>sigma</code> = <strong>8.3333</strong> (25 / 3)</li>
<li>ordinal at default = <strong>0.0</strong> (25 − 3 × 8.3333)</li>
</ul>
<p>Since everyone starts identical, teams are balanced until real match
results start moving individual ratings.</p>

<h3>Balancing females</h3>
<p>Set <code>"balance_females": true</code> at the top level of the request to
keep the number of females equal in both teams. It works with every endpoint
and is <strong>disabled by default</strong>. With an odd number of females one
team has exactly one more; with a single female she simply lands in one of the
teams; with zero females the flag changes nothing.</p>

<h3>Validation &amp; limits</h3>
<ul>
<li>At least 2 players are required; any malformed input (missing
<code>players</code>, non-numeric <code>mu</code>/<code>sigma</code>,
<code>male</code> outside 0/1, non-boolean <code>balance_females</code>)
is answered with <strong>HTTP 400</strong> and a JSON
<code>{"error": "..."}</code> body.</li>
<li><code>avg</code> tries every combination, so it accepts at most
<strong>24 players</strong> (400 above that); rand/topdown have no cap.</li>
<li>Request bodies over 1&nbsp;MB are rejected with 413.</li>
<li>Successful responses are <code>application/json</code>, HTTP 200.</li>
</ul>

<h3>Create a JSON file</h3>
<pre>
{
  "balance_females": false,
  "players":
     {
       "1": { "mu": 25, "sigma": 8.333, "male": 0 },
       "2": { "mu": 20, "sigma": 8.333, "male": 0 },
       "3": { "male": 0 }
     }
}
</pre>

<h3>Endpoints</h3>
<ul>
<li>rand - split players into teams randomly</li>
<li>topdown - snake draft by OpenSkill ordinal</li>
<li>avg - balance the two teams by average OpenSkill ordinal</li>
</ul>

<h4>Example requests</h4>
<pre>
curl --json "$(cat data3.json)" http://127.0.0.1:5000/rand | jq
curl --json "$(cat data12.json)" http://127.0.0.1:5000/topdown | jq
curl --json "$(cat data12.json)" http://127.0.0.1:5000/avg | jq
</pre>

<h2>Development</h2>
<pre>
python3 -m venv venv && venv/bin/pip install -r requirements-dev.txt
venv/bin/ruff check . && venv/bin/ruff format --check .   # linter
venv/bin/pytest                                           # unit + integration tests
</pre>
<p>CI (GitHub Actions, <code>.github/workflows/ci.yml</code>) runs ruff and
pytest on every push and pull request; a push to <code>master</code>
additionally builds and publishes the multi-arch (amd64+arm64) Docker image to
Docker Hub. Publishing needs the repo secrets
<code>DOCKERHUB_USERNAME</code> and <code>DOCKERHUB_TOKEN</code>. The
container runs gunicorn as an unprivileged user.</p>
