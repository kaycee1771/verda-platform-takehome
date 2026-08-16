# ADR 0003: Use Three Schedulable RKE2 Server Nodes per Cluster

- **Status:** Accepted
- **Date:** 2026-08-16
- **Owners:** Platform architecture
- **Blocking gates:** Final CPU shape depends on authenticated account inventory and cost

## Context

RKE2 embedded etcd needs an odd server count for quorum. Dedicated worker pools would improve isolation but increase the footprint before proving mandatory requirements.

## Decision

Each implemented cluster uses three RKE2 server nodes running control-plane, etcd, and worker roles. Do not use spot capacity for these nodes. Apply reservations, requests/limits, priorities, spread, PDBs, and capacity headroom.

## Alternatives considered

- **One server:** insufficient quorum/failure evidence.
- **Three servers plus workers:** better isolation, higher cost and operational scope.
- **Five servers:** no additional failure tolerance over three for the take-home and more cost.

## Consequences

- One server can fail while two retain etcd quorum.
- Platform/workload pressure can contend with control-plane processes.
- Stateful/application HA remains a separate property and must be tested independently.

## Validation evidence

Official RKE2 HA guidance reviewed 2026-08-16 states three servers are recommended and server nodes are schedulable by default. Live proof requires allocatable-headroom analysis and a controlled one-node drain/process-loss test.

## Production evolution

Use dedicated control-plane nodes and autoscaled/segmented worker pools, with separate GPU pools and topology-aware capacity.
