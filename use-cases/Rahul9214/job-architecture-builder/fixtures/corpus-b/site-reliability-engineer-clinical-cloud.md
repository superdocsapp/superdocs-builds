# Site Reliability Engineer, Clinical Cloud

## Team
Clinical Reliability

## Role purpose
Keep Meridian's clinical cloud environments inside agreed SLOs so care teams are not blocked by platform outages during clinic hours.

## Responsibilities
- Define SLOs for clinical-critical paths (chart open, order entry, results delivery) with product and clinical operations.
- Own incident command for Sev-1 clinical-cloud events, including paging executives when chart access is down.
- Build automation for cluster recovery, backup restore drills, and region failover tests.
- Review change windows against clinic schedules; block deploys that collide with peak order-entry hours.
- Maintain runbooks that a night-shift engineer can execute without tribal knowledge.
- Reduce toil in certificate rotation, capacity, and noisy alerts.
- Participate in tabletop exercises with clinical operations for downtime communications.

## Scope and autonomy
You own reliability of the clinical cloud substrate. You can freeze a deploy, demand a rollback, and require an error-budget policy. You do not set clinical product features. Major multi-region architecture still needs a recorded design review with platform engineering.

## Leadership and management
No direct reports. During incidents you can direct engineers who do not report to you until the incident is closed. You do not write their reviews.

## Stakeholders
- Clinical operations (clinic hours and downtime comms)
- Platform engineers who ship the services you watch
- Information security during suspected availability attacks
- Vendor cloud support
- Clinical product managers, for error-budget trade-offs
- Hospital IT contacts during shared outages

## Requirements
- Production SRE or equivalent experience on systems with a human-safety or clinical-availability bar.
- Incident-command skill, including calm communication under paging load.
- Infrastructure-as-code and observability fluency.
- Respect for change control that is stricter than a typical consumer app.
