// 1) Orphan servers (has traffic but no CMDB link)
MATCH (s:Server)
WHERE (s)--(:Server)  // participates in any connection
AND NOT ( (:Application)-[:RUNS_ON|:DEPENDS_ON]->(s) )
RETURN s.hostname, s.type, s.os, s.lifecycle_state;

// 2) EOL blast radius (variable depth)
MATCH (e:EOL)-[:AFFECTS]->(h:Server)
MATCH p=(h)-[:CONNECTS_TO*1..4]->(down:Server)
RETURN e.component as eol_component, h.hostname as affected_host, count(DISTINCT down) as impacted_hosts;

// 3) Modernization candidates (simple scoring components)
MATCH (s:Server)
OPTIONAL MATCH (e:EOL)-[:AFFECTS]->(s)
WITH s, max(CASE e.severity WHEN 'Critical' THEN 3 WHEN 'High' THEN 2 WHEN 'Medium' THEN 1 ELSE 0 END) as eol_sev
OPTIONAL MATCH (t:Ticket)-[:RELATES_TO]->(s)
WITH s, eol_sev, count(t) as ticket_cnt
RETURN s.hostname, eol_sev, ticket_cnt
ORDER BY eol_sev DESC, ticket_cnt DESC, s.hostname;

// 4) Find hidden integration: orphan -> billing DB path
MATCH p=(o:Server {hostname:'orphan-legacy-01'})-[:CONNECTS_TO]->(db:Server)
RETURN p;
