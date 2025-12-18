
import streamlit as st
import pandas as pd
import networkx as nx
from pathlib import Path
from datetime import datetime, date

st.set_page_config(page_title="Graph Modernization Insights PoC", layout="wide")

DATA_DIR = Path(__file__).parent / "data"

@st.cache_data
def load():
    dfs = {
        "applications": pd.read_csv(DATA_DIR/"applications.csv"),
        "servers": pd.read_csv(DATA_DIR/"servers.csv"),
        "cmdb": pd.read_csv(DATA_DIR/"cmdb_links.csv"),
        "network": pd.read_csv(DATA_DIR/"network_connections.csv"),
        "eol": pd.read_csv(DATA_DIR/"eol.csv"),
        "tickets": pd.read_csv(DATA_DIR/"tickets.csv"),
        "perf": pd.read_csv(DATA_DIR/"performance.csv"),
        "costs": pd.read_csv(DATA_DIR/"costs.csv"),
        "docs": pd.read_csv(DATA_DIR/"documents.csv"),
    }
    return dfs

def build_graph(d):
    G = nx.DiGraph()

    # Nodes
    for _, r in d["applications"].iterrows():
        G.add_node(r["app_id"], kind="Application", label=r["app_name"], **r.to_dict())

    for _, r in d["servers"].iterrows():
        G.add_node(r["hostname"], kind="Server", label=r["hostname"], **r.to_dict())

    for _, r in d["tickets"].iterrows():
        G.add_node(r["ticket_id"], kind="Ticket", label=r["ticket_id"], **r.to_dict())

    for _, r in d["docs"].iterrows():
        G.add_node(r["doc_id"], kind="Document", label=r["title"], **r.to_dict())

    for _, r in d["eol"].iterrows():
        key = f"EOL::{r['component']}::{r['matches_hostname']}"
        G.add_node(key, kind="EOL", label=r["component"], **r.to_dict())

    # Edges: CMDB links
    for _, r in d["cmdb"].iterrows():
        G.add_edge(r["app_id"], r["hostname"], rel=r["relation"])

    # Edges: network connections
    for _, r in d["network"].iterrows():
        G.add_edge(r["src"], r["dst"], rel="CONNECTS_TO", protocol=r["protocol"], port=int(r["port"]), avg_rps=float(r["avg_rps"]), p95_ms=float(r["p95_ms"]))

    # Edges: ticket to CI
    for _, r in d["tickets"].iterrows():
        G.add_edge(r["ticket_id"], r["ci"], rel="RELATES_TO")

    # Edges: doc to entity (app or host)
    for _, r in d["docs"].iterrows():
        G.add_edge(r["doc_id"], r["related_to"], rel="DOCUMENTS")

    # Edges: eol to host
    for _, r in d["eol"].iterrows():
        key = f"EOL::{r['component']}::{r['matches_hostname']}"
        G.add_edge(key, r["matches_hostname"], rel="AFFECTS")

    return G

def orphan_servers(G):
    # servers that have network traffic but no incoming CMDB edges from any application
    servers_with_traffic = set([n for n, a in G.nodes(data=True) if a.get("kind")=="Server" and (G.in_degree(n)>0 or G.out_degree(n)>0)])
    mapped_servers = set()
    for u,v,a in G.edges(data=True):
        if a.get("rel") in ("RUNS_ON","DEPENDS_ON") and G.nodes[u].get("kind")=="Application" and G.nodes[v].get("kind")=="Server":
            mapped_servers.add(v)
    orphan = sorted(list(servers_with_traffic - mapped_servers))
    return orphan

def blast_radius_from_eol(G, max_hops=4):
    # Starting from EOL nodes -> affected host -> traverse CONNECTS_TO outward up to max_hops
    eol_nodes = [n for n,a in G.nodes(data=True) if a.get("kind")=="EOL"]
    rows=[]
    for e in eol_nodes:
        affected = [v for _,v,a in G.out_edges(e, data=True) if a.get("rel")=="AFFECTS"]
        for host in affected:
            # BFS outward on CONNECTS_TO edges
            visited = {host:0}
            q=[host]
            while q:
                cur=q.pop(0)
                depth=visited[cur]
                if depth>=max_hops: 
                    continue
                for _,nxt,a in G.out_edges(cur, data=True):
                    if a.get("rel")!="CONNECTS_TO": 
                        continue
                    if nxt not in visited:
                        visited[nxt]=depth+1
                        q.append(nxt)
            impacted = [n for n,d in visited.items() if n!=host and G.nodes[n].get("kind")=="Server"]
            rows.append({"eol_component":G.nodes[e].get("component"), "affected_host":host, "impacted_hosts_count":len(impacted), "impacted_hosts":", ".join(sorted(impacted))})
    return pd.DataFrame(rows)

def modernization_candidates(G):
    # Simple scoring combining: EOL severity, ticket volume, p95 latency, and centrality
    # (This is a PoC heuristic; in prod you'd use ML / graph embeddings.)
    import numpy as np

    # Centrality on server subgraph
    server_nodes=[n for n,a in G.nodes(data=True) if a.get("kind")=="Server"]
    H = G.subgraph(server_nodes).copy()
    # keep CONNECTS_TO only
    drop=[]
    for u,v,a in H.edges(data=True):
        if a.get("rel")!="CONNECTS_TO":
            drop.append((u,v))
    H.remove_edges_from(drop)

    if H.number_of_edges() > 0:
        bc = nx.betweenness_centrality(H)
    else:
        bc = {n:0.0 for n in server_nodes}

    # Tickets per host
    ticket_counts={n:0 for n in server_nodes}
    for u,v,a in G.edges(data=True):
        if a.get("rel")=="RELATES_TO" and G.nodes[u].get("kind")=="Ticket" and v in ticket_counts:
            ticket_counts[v]+=1

    # EOL severity
    sev_map={"Critical":3, "High":2, "Medium":1, "Low":0}
    eol_sev={n:0 for n in server_nodes}
    for e,host,a in G.edges(data=True):
        if a.get("rel")=="AFFECTS" and host in eol_sev:
            eol_sev[host]=max(eol_sev[host], sev_map.get(G.nodes[e].get("severity","Low"),0))

    # Performance p95 from edge attr if present (fallback 0)
    perf_p95={n:0.0 for n in server_nodes}
    for u,v,a in G.edges(data=True):
        if a.get("rel")=="CONNECTS_TO" and isinstance(a.get("p95_ms"), (int,float)):
            perf_p95[v]=max(perf_p95[v], float(a["p95_ms"]))

    # Compute score
    rows=[]
    for s in server_nodes:
        score = 30*eol_sev[s] + 12*ticket_counts[s] + 0.08*perf_p95[s] + 40*bc.get(s,0.0)
        rows.append({
            "hostname":s,
            "eol_severity":eol_sev[s],
            "ticket_count":ticket_counts[s],
            "max_inbound_p95_ms":round(perf_p95[s],1),
            "betweenness":round(bc.get(s,0.0),4),
            "modernize_score":round(score,2)
        })
    df=pd.DataFrame(rows).sort_values("modernize_score", ascending=False)
    return df

def subgraph_for_app(G, app_id):
    # include app, its mapped servers, and 1-hop network neighborhood
    nodes=set([app_id])
    for _,srv,a in G.out_edges(app_id, data=True):
        if a.get("rel") in ("RUNS_ON","DEPENDS_ON"):
            nodes.add(srv)
            # 1 hop from server
            nodes.update([v for _,v,ea in G.out_edges(srv, data=True) if ea.get("rel")=="CONNECTS_TO"])
            nodes.update([u for u,_,ea in G.in_edges(srv, data=True) if ea.get("rel")=="CONNECTS_TO"])
    return G.subgraph(nodes).copy()

def render_edges_table(G, nodes=None):
    rows=[]
    for u,v,a in G.edges(data=True):
        if nodes and (u not in nodes or v not in nodes): 
            continue
        rows.append({"from":u, "to":v, "rel":a.get("rel"), "protocol":a.get("protocol",""), "port":a.get("port",""), "avg_rps":a.get("avg_rps",""), "p95_ms":a.get("p95_ms","")})
    return pd.DataFrame(rows)

d = load()
G = build_graph(d)

st.title("Graph Modernization Insights PoC")
st.caption("Demonstrates why a graph database is useful for connecting CMDB, ServiceNow, network flows, EOL, performance, cost & documents.")

tab1, tab2, tab3, tab4 = st.tabs(["1) Overview", "2) Orphan/Unknown Apps", "3) EOL Blast Radius", "4) Modernization Candidates"])

with tab1:
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Applications", len(d["applications"]))
    c2.metric("Servers", len(d["servers"]))
    c3.metric("Network edges", len(d["network"]))
    c4.metric("Tickets", len(d["tickets"]))

    st.subheader("Entity tables (sample data)")
    st.write("Applications"); st.dataframe(d["applications"], use_container_width=True)
    st.write("Servers"); st.dataframe(d["servers"], use_container_width=True)
    st.write("CMDB Links"); st.dataframe(d["cmdb"], use_container_width=True)
    st.write("Network Connections"); st.dataframe(d["network"], use_container_width=True)

with tab2:
    st.subheader("Find orphan servers (traffic seen but not mapped in CMDB)")
    orphans = orphan_servers(G)
    st.dataframe(pd.DataFrame({"orphan_hostname": orphans}), use_container_width=True)
    st.write("Why it matters: these often represent undocumented workloads, hidden integrations, or stale CMDB mappings.")
    if orphans:
        chosen = st.selectbox("Inspect an orphan host", orphans)
        neigh = list(set([chosen] + [v for _,v,_ in G.out_edges(chosen, data=True)] + [u for u,_,_ in G.in_edges(chosen, data=True)]))
        st.write("Neighborhood edges")
        st.dataframe(render_edges_table(G, nodes=set(neigh)), use_container_width=True)

with tab3:
    st.subheader("Trace blast radius from EOL components (multi-hop dependency view)")
    hops = st.slider("Max hops (CONNECTS_TO)", 1, 6, 4)
    df = blast_radius_from_eol(G, max_hops=hops)
    st.dataframe(df, use_container_width=True)
    st.write("This is the kind of recursive, variable-depth query that becomes painful with SQL joins, but is natural in graphs.")

with tab4:
    st.subheader("Rank modernization candidates (simple PoC scoring)")
    st.write("Score combines: EOL severity, ticket volume, latency, and graph centrality (betweenness).")
    cand = modernization_candidates(G)
    st.dataframe(cand, use_container_width=True)

    st.write("Inspect an application subgraph (CMDB + 1-hop network context)")
    apps = d["applications"]["app_id"].tolist()
    app_id = st.selectbox("Application", apps, index=0)
    sg = subgraph_for_app(G, app_id)
    st.dataframe(render_edges_table(sg), use_container_width=True)

st.markdown("---")
st.caption("Next step: swap NetworkX with Neo4j/Neptune/TigerGraph for scale + concurrent queries, keeping the same graph model.")
