# Split players to two teams based on different algorithms

## Build and Start docker container
docker build --tag python-docker .; docker run -d -p 5000:5000 python-docker

# Send in the list of players in JSON format and get back players split in the two teams
curl http://127.0.0.1:5000/random -X POST -H 'Content-Type: application/json' --data-b "$(cat data3.json)" | jq
curl http://127.0.0.1:5000/topdown -X POST -H 'Content-Type: application/json' --data-b "$(cat data12.json)" | jq
curl http://127.0.0.1:5000/average -X POST -H 'Content-Type: application/json' --data-b "$(cat data12.json)" | jq
