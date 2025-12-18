# Graph Modernization Insights PoC (AssessAI-style demo)

This PoC demonstrates **why graph databases** are a strong fit for connecting:
CMDB + ServiceNow + network flows + EOL risk + performance + cost + runbooks/docs,
and then running relationship-heavy insights such as:
- Orphan/unknown servers (traffic exists, CMDB missing)
- EOL blast radius (multi-hop dependencies)
- Modernization candidate ranking (risk + ops + graph centrality)

## Run locally
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Data
Sample CSVs are in `data/`:
- applications.csv
- servers.csv
- cmdb_links.csv
- network_connections.csv
- eol.csv
- tickets.csv
- performance.csv
- costs.csv
- documents.csv

## Optional: Neo4j implementation (recommended for leadership demo)
If you want to show a *real* Graph DB:
1) Start Neo4j:
```bash
docker compose up -d
```
2) Open Neo4j Browser: http://localhost:7474
3) Run `neo4j_import.cypher` from `neo4j/` to load sample nodes/edges.
4) Try the Cypher queries in `neo4j/queries.cypher`.

The Streamlit UI can remain the same; you would replace the NetworkX builder with Neo4j queries.
