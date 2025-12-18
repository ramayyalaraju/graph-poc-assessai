// Run in Neo4j Browser after docker compose up
// Assumes CSVs are mounted to /var/lib/neo4j/import

// Constraints
CREATE CONSTRAINT app_id IF NOT EXISTS FOR (a:Application) REQUIRE a.app_id IS UNIQUE;
CREATE CONSTRAINT host_id IF NOT EXISTS FOR (s:Server) REQUIRE s.hostname IS UNIQUE;

// Load Applications
LOAD CSV WITH HEADERS FROM 'file:///applications.csv' AS row
MERGE (a:Application {app_id: row.app_id})
SET a.app_name=row.app_name, a.business_unit=row.business_unit, a.criticality=row.criticality, a.tech_stack=row.tech_stack, a.owner_team=row.owner_team;

// Load Servers
LOAD CSV WITH HEADERS FROM 'file:///servers.csv' AS row
MERGE (s:Server {hostname: row.hostname})
SET s.env=row.env, s.os=row.os, s.type=row.type, s.ip=row.ip, s.lifecycle_state=row.lifecycle_state, s.warranty_end=row.warranty_end;

// CMDB relationships
LOAD CSV WITH HEADERS FROM 'file:///cmdb_links.csv' AS row
MATCH (a:Application {app_id: row.app_id})
MATCH (s:Server {hostname: row.hostname})
CALL {
  WITH a,s,row
  WITH a,s,row WHERE row.relation='RUNS_ON'
  MERGE (a)-[:RUNS_ON]->(s)
  RETURN 1
}
CALL {
  WITH a,s,row
  WITH a,s,row WHERE row.relation='DEPENDS_ON'
  MERGE (a)-[:DEPENDS_ON]->(s)
  RETURN 1
}
RETURN count(*) as cmdb_loaded;

// Network connections
LOAD CSV WITH HEADERS FROM 'file:///network_connections.csv' AS row
MATCH (src:Server {hostname: row.src})
MATCH (dst:Server {hostname: row.dst})
MERGE (src)-[c:CONNECTS_TO {protocol: row.protocol, port: toInteger(row.port)}]->(dst)
SET c.avg_rps=toFloat(row.avg_rps), c.p95_ms=toFloat(row.p95_ms);

// Tickets
LOAD CSV WITH HEADERS FROM 'file:///tickets.csv' AS row
MERGE (t:Ticket {ticket_id: row.ticket_id})
SET t.source=row.source, t.type=row.type, t.priority=row.priority, t.opened=row.opened, t.short_desc=row.short_desc
WITH t,row
MATCH (s:Server {hostname: row.ci})
MERGE (t)-[:RELATES_TO]->(s);

// EOL
LOAD CSV WITH HEADERS FROM 'file:///eol.csv' AS row
MERGE (e:EOL {component: row.component, matches_hostname: row.matches_hostname})
SET e.category=row.category, e.eol_date=row.eol_date, e.severity=row.severity
WITH e,row
MATCH (s:Server {hostname: row.matches_hostname})
MERGE (e)-[:AFFECTS]->(s);

// Documents
LOAD CSV WITH HEADERS FROM 'file:///documents.csv' AS row
MERGE (d:Document {doc_id: row.doc_id})
SET d.doc_type=row.doc_type, d.title=row.title, d.text=row.text, d.related_to=row.related_to
WITH d,row
// related_to may be app_id or hostname
OPTIONAL MATCH (a:Application {app_id: row.related_to})
OPTIONAL MATCH (s:Server {hostname: row.related_to})
FOREACH (_ IN CASE WHEN a IS NULL THEN [] ELSE [1] END | MERGE (d)-[:DOCUMENTS]->(a))
FOREACH (_ IN CASE WHEN s IS NULL THEN [] ELSE [1] END | MERGE (d)-[:DOCUMENTS]->(s));
