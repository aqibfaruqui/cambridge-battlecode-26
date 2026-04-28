import os
import subprocess
from time import sleep
import random
exclude_id = ['73598a2e-591b-4f37-9dfc-b079c7517c0d', 'e32d3cc9-5c40-4d8a-9177-18003cb41aaa', 'ab8198de-3062-4789-b1ce-653e3d420efb'] # Our team ID, drop table and test team ID

def run_cmd(command, env):
    cmd = subprocess.list2cmdline(command)
    result = subprocess.run(
        cmd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
        env=env
    )

    return result.stdout

import re
def parse_ascii_table(text):
    rows = []
    lines = text.splitlines()
    
    for line in lines:
        line = line.strip()
        
        # Only process lines that start with "| " and are not the header separator
        if line.startswith("│") and not set(line[1:-1]).issubset({"-", "+"}):
            # Split by | and strip spaces
            parts = [p.strip() for p in line.split("│")]
            
            # There will be empty strings at start/end due to leading/trailing |
            if len(parts) < 7:
                continue
            
            # Skip the header row
            if parts[1] == "#":
                continue
            
            # Parse row
            row = {
                "rank": int(parts[1]),
                "team": parts[2],
                "rating": int(parts[3]),
                "matches": int(parts[4]),
                "category": parts[5],
                "region": parts[6],
            }
            rows.append(row)
    
    return rows

def parse_ascii_tableid(text):
    rows = []

    for line in text.splitlines():
        line = line.strip()
        # Skip border lines and header row
        if line.startswith("+") or line.startswith("│-") or "Team ID" in line:
            continue

        if line.startswith("│"):
            # Split on | and strip spaces
            parts = [p.strip() for p in line.split("│")]

            # Remove empty strings from leading/trailing pipes
            parts = [p for p in parts if p]

            if len(parts) != 6:
                continue  # skip malformed rows

            row = {
                "team_id": parts[0],
                "name": parts[1],
                "category": parts[2],
                "rating": int(parts[3]),
                "matches": int(parts[4]),
                "region": parts[5],
            }
            rows.append(row)

    return rows



command = ["cambc", "ladder", "--region", "uk", "--limit", "14", "--category", "main"]
env = os.environ.copy()
env["COLUMNS"] = "1000"
env["LINES"] = "100000"


output = run_cmd(command, env)
teas=parse_ascii_table(output)
teams=[]
for t in teas:
    cmds=["cambc","team","search",t["team"]]
    output2 = run_cmd(cmds, env)
    team_id = parse_ascii_tableid(output2)[0]["team_id"]
    if team_id not in exclude_id:
        teams.append({"name": t["team"], "rank": t["rank"], "id": team_id})

print(teams)

while True:
    team = random.choice(teams)
    command = ["cambc", "match", "unrated", team["id"]]
    print(f"Running scrims against {team["name"]} (rank {team["rank"]})")
    for i in range(5):
        output = run_cmd(command, env)
    sleep(600)
