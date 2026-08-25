/**
 * The mock ServiceNow instance's `change_request` table.
 *
 * Rows are stored the way ServiceNow stores them: ServiceNow field names,
 * reference fields as bare sys_ids, `state` as a numeric code, dates in the
 * instance format "YYYY-MM-DD HH:MM:SS" in UTC. The mock Table API in
 * `mockApi.js` serves them and applies `sysparm_display_value` the way a real
 * instance does, so nothing downstream can tell the difference.
 *
 * The set is deliberately varied: closed and open changes, so filtering on
 * `state=3` has something to filter; several close codes; and two records that
 * exist to exercise failure paths.
 */

/** Referenced tables, so the mock can resolve a sys_id to its display value. */
export const referenceTables = {
  cmdb_ci: {
    "3a1f77c2b1d54e0a": "PROD-API-GATEWAY-01",
    "77d0a4e1c9b24f56": "PROD-ID-DB-PRIMARY",
    "9b41e7d0a2c34851": "PAYMENTS-EDGE-LB-02",
    "2d8c60fb7e194a33": "PROD-K8S-CLUSTER-A",
    "58f3a91c4d0b47e2": "PROD-ORDER-SVC",
    "e40b19d7c2a8435f": "ANALYTICS-WH-CLUSTER",
    "8c72d4b0e15a4936": "STAGE-CACHE-REDIS",
    "1f5a93e7b8d0426c": "PROD-NOTIFY-WORKER",
    "6b91c07d3e2a4f18": "PROD-SEARCH-INDEX-02",
    "0e3d82a1f74b4c95": "PROD-BILLING-QUEUE",
    "c5a70e28d9134b6f": "PROD-CDN-ORIGIN-EU",
    "47f2b98c0a6d41e3": "PROD-AUTH-SVC-01"
  },
  sys_user: {
    a11c2e93: "Asha Rao",
    b73d1f08: "Marcus Lee",
    c48e7a20: "Nina Patel",
    d92f4c81: "Daniel Cho",
    e51a70bd: "Priya Shah",
    f28c6b04: "Olivia Chen",
    "0a4d17ce": "Hannah Brooks",
    "3b8e21fa": "Tomas Alvarez",
    "5c0b93d7": "Ravi Menon",
    "7e14a6c2": "Sofia Iversen"
  },
  sys_user_group: {
    d81f0b44: "Platform Engineering",
    e2a94c17: "Data Platform",
    f70b2d63: "Payments Infrastructure",
    a3c81e57: "Platform Engineering",
    b6d20f39: "Order Management",
    c19e4a72: "Analytics Engineering",
    d47f2b60: "Platform Engineering",
    e58a1c04: "Messaging",
    f0b73e91: "Search Platform",
    "1d92e0b4": "Billing Platform",
    "2f6c81ad": "Edge Delivery",
    "3a05f7be": "Identity Platform"
  }
};

/** ServiceNow `change_request.state` codes. */
export const STATE_CODES = {
  "-5": "New",
  "-4": "Assess",
  "-3": "Authorize",
  "-2": "Scheduled",
  "-1": "Implement",
  "0": "Review",
  "3": "Closed",
  "4": "Canceled"
};

export const changeRequestRows = [
  {
    sys_id: "8f4d1b2c9a7e4d3f8b21c05e6a1d4471",
    number: "CHG0010042",
    short_description: "Upgrade production API gateway",
    cmdb_ci: "3a1f77c2b1d54e0a",
    work_notes:
      "Maintenance window completed. Traffic was drained before upgrade and restored after health checks passed.",
    close_code: "Successful",
    state: "3",
    requested_by: "a11c2e93",
    assignment_group: "d81f0b44",
    start_date: "2026-08-18 22:00:00",
    end_date: "2026-08-18 23:00:00",
    risk: "Moderate",
    sys_updated_on: "2026-08-18 23:14:02"
  },
  {
    sys_id: "1c9b58aa2f7c46d1a0e3b7d9c4f21188",
    number: "CHG0010043",
    short_description: "Patch customer identity database",
    cmdb_ci: "77d0a4e1c9b24f56",
    work_notes:
      "Patch bundle applied to primary and standby nodes. Replication lag stayed under two seconds throughout validation.",
    close_code: "Successful",
    state: "3",
    requested_by: "b73d1f08",
    assignment_group: "e2a94c17",
    start_date: "2026-08-19 01:00:00",
    end_date: "2026-08-19 02:15:00",
    risk: "High",
    sys_updated_on: "2026-08-19 02:31:47"
  },
  {
    sys_id: "5e2c81d47b9a41f0a6c8d3e2b7104492",
    number: "CHG0010044",
    short_description: "Rotate TLS certificates for payments edge",
    cmdb_ci: "9b41e7d0a2c34851",
    work_notes:
      "New certificates deployed and verified with synthetic payment checks. No client handshake errors observed after cutover.",
    close_code: "Successful",
    state: "3",
    requested_by: "c48e7a20",
    assignment_group: "f70b2d63",
    start_date: "2026-08-19 03:30:00",
    end_date: "2026-08-19 04:00:00",
    risk: "High",
    sys_updated_on: "2026-08-19 04:12:09"
  },
  {
    sys_id: "b607d3e94c1a487fb2d05a6e1c937703",
    number: "CHG0010045",
    short_description: "Expand Kubernetes worker capacity",
    cmdb_ci: "2d8c60fb7e194a33",
    work_notes:
      "Six worker nodes added to the production pool. Existing workloads remained balanced and cluster autoscaler limits were updated.",
    close_code: "Successful",
    state: "3",
    requested_by: "d92f4c81",
    assignment_group: "a3c81e57",
    start_date: "2026-08-19 05:00:00",
    end_date: "2026-08-19 05:45:00",
    risk: "Low",
    sys_updated_on: "2026-08-19 06:02:55"
  },
  {
    sys_id: "cc1a45f0b83d4e2790a7d6c5e2f81824",
    number: "CHG0010046",
    short_description: "Enable enhanced logging for order service",
    cmdb_ci: "58f3a91c4d0b47e2",
    work_notes:
      "Structured request logging enabled for order create and update paths. Sampling stayed at the approved rate and storage alarms remained normal.",
    close_code: "Successful",
    state: "3",
    requested_by: "e51a70bd",
    assignment_group: "b6d20f39",
    start_date: "2026-08-19 07:00:00",
    end_date: "2026-08-19 07:30:00",
    risk: "Low",
    sys_updated_on: "2026-08-19 07:48:20"
  },
  {
    sys_id: "7a03e5b1d64f4c9880b1e2a7c5d30916",
    number: "CHG0010047",
    short_description: "Migrate analytics warehouse snapshot",
    cmdb_ci: "e40b19d7c2a8435f",
    work_notes:
      "Snapshot restored into the new warehouse cluster and row counts matched the approved reconciliation report.",
    close_code: "Successful",
    state: "3",
    requested_by: "f28c6b04",
    assignment_group: "c19e4a72",
    start_date: "2026-08-19 08:30:00",
    end_date: "2026-08-19 10:00:00",
    risk: "Moderate",
    sys_updated_on: "2026-08-19 10:22:31"
  },
  {
    sys_id: "e2c740b18a5d4f39b0c6a1e7d3428855",
    number: "CHG0010048",
    short_description: "Reindex product search cluster",
    cmdb_ci: "6b91c07d3e2a4f18",
    work_notes:
      "Full reindex completed against the standby index and promoted after relevance sampling matched the baseline within tolerance.",
    close_code: "Successful with issues",
    state: "3",
    requested_by: "5c0b93d7",
    assignment_group: "f0b73e91",
    start_date: "2026-08-19 11:00:00",
    end_date: "2026-08-19 13:20:00",
    risk: "Moderate",
    sys_updated_on: "2026-08-19 13:41:08"
  },
  {
    sys_id: "3f81a06c2e9b44d7a5f0c83b1d6e2977",
    number: "CHG0010049",
    short_description: "Drain and replace billing queue broker",
    cmdb_ci: "0e3d82a1f74b4c95",
    work_notes:
      "Broker node replaced after the queue was drained to zero depth. No billing events were lost and consumer offsets resumed cleanly.",
    close_code: "Successful",
    state: "3",
    requested_by: "7e14a6c2",
    assignment_group: "1d92e0b4",
    start_date: "2026-08-19 14:00:00",
    end_date: "2026-08-19 15:05:00",
    risk: "High",
    sys_updated_on: "2026-08-19 15:27:44"
  },
  {
    sys_id: "9c05e73a1b8f42d6907e2c4a5b13f068",
    number: "CHG0010050",
    short_description: "Fail over EU CDN origin to secondary region",
    cmdb_ci: "c5a70e28d9134b6f",
    work_notes:
      "Origin failover exercised as scheduled. Cache hit ratio recovered to baseline within eleven minutes of the cutover.",
    close_code: "Successful",
    state: "3",
    requested_by: "0a4d17ce",
    assignment_group: "2f6c81ad",
    start_date: "2026-08-19 16:00:00",
    end_date: "2026-08-19 16:40:00",
    risk: "Moderate",
    sys_updated_on: "2026-08-19 17:01:12"
  },
  {
    sys_id: "44b8c02e7d1f49a5b3e6c8d0a217f635",
    number: "CHG0010053",
    short_description: "Roll back staging cache configuration",
    cmdb_ci: "8c72d4b0e15a4936",
    work_notes:
      "Cache timeout reverted to the previous value after integration tests showed elevated retry volume. Staging traffic stabilized after rollback.",
    close_code: "Rolled back",
    state: "3",
    requested_by: "0a4d17ce",
    assignment_group: "d47f2b60",
    start_date: "2026-08-19 20:30:00",
    end_date: "2026-08-19 20:55:00",
    risk: "Low",
    sys_updated_on: "2026-08-19 21:10:33"
  },
  {
    // Deliberately incomplete: exercises the validation gate before anything is
    // sent to SuperDocs. Closed with no work notes and no close code.
    sys_id: "9de1f7a2c05b43e8912d4a6b7c08e551",
    number: "CHG0010054",
    short_description: "Emergency restart of notification worker",
    cmdb_ci: "1f5a93e7b8d0426c",
    work_notes: "",
    close_code: "",
    state: "3",
    requested_by: "3b8e21fa",
    assignment_group: "e58a1c04",
    start_date: "2026-08-19 22:10:00",
    end_date: "2026-08-19 22:18:00",
    risk: "Moderate",
    sys_updated_on: "2026-08-19 22:20:04"
  },
  {
    // Still open, so it never reaches the queue: the queue asks for state=3,
    // which is only true of a mock that actually applies sysparm_query.
    sys_id: "aa17e39c05b2417d8f6c1e0b93d2a744",
    number: "CHG0010055",
    short_description: "Consolidate authentication service replicas",
    cmdb_ci: "47f2b98c0a6d41e3",
    work_notes: "Change scheduled. Implementation has not started.",
    close_code: "",
    state: "-2",
    requested_by: "7e14a6c2",
    assignment_group: "3a05f7be",
    start_date: "2026-08-24 02:00:00",
    end_date: "2026-08-24 03:30:00",
    risk: "High",
    sys_updated_on: "2026-08-20 09:15:00"
  },
  {
    sys_id: "d80b1f4e6a29457c93e5a0d7b2c61f39",
    number: "CHG0010056",
    short_description: "Increase billing queue consumer concurrency",
    cmdb_ci: "0e3d82a1f74b4c95",
    work_notes: "Consumer concurrency raised in a canary partition pending review.",
    close_code: "",
    state: "-1",
    requested_by: "5c0b93d7",
    assignment_group: "1d92e0b4",
    start_date: "2026-08-22 18:00:00",
    end_date: "2026-08-22 19:00:00",
    risk: "Low",
    sys_updated_on: "2026-08-22 18:44:19"
  }
];
