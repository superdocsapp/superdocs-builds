# incident 7/22 (rough timeline, fill in later)

~14:02 - alerts firing, api latency p99 spiking
~14:05 - on call (me) paged
~14:11 - identified: db connection pool exhausted
~14:20 - rolled back deploy from earlier today
~14:26 - latency back to normal

root cause: new query missing an index, was fine in staging bc smaller dataset

todo
- add index (ticket?)
- add staging data volume closer to prod
- postmortem doc - who owns this

impact: ~24min degraded, no full outage, maybe 200 users affected?? not exact
