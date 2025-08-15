# Milestone: Apache Polaris Catalog Migration Decision

**Date**: January 12, 2025  
**Status**: Completed  
**Duration**: 4 hours  
**Impact**: Major architectural decision for data platform

## Overview

After encountering a critical bug in the GetInData Hive Metastore Helm chart and investigating modern alternatives, the decision was made to migrate from traditional Hive Metastore to Apache Polaris as the catalog implementation for Apache Iceberg tables.

## Motivation

The migration was triggered by:
1. **Technical Blocker**: GetInData Hive Metastore Helm chart v0.1.0 has duplicate label bug preventing deployment
2. **Modernization**: Hive Metastore is legacy technology not designed for cloud-native environments
3. **Simplification**: Apache Polaris offers lightweight, purpose-built Iceberg catalog implementation
4. **Future-proofing**: Polaris implements Iceberg REST API standard for compatibility

## Investigation Process

### Technologies Evaluated

1. **Apache Polaris** (Selected)
   - Open-source under Apache 2.0 license
   - Native Iceberg REST API implementation
   - Kubernetes-native with Helm charts
   - Lightweight compared to Hive

2. **Project Nessie**
   - Git-like versioning for data
   - More complex than needed for current use case
   - Mature but heavier solution

3. **Unity Catalog OSS**
   - Limited Kubernetes support
   - Better suited for Databricks environments
   - OSS version not equivalent to commercial product

4. **Traditional Hive Metastore**
   - Current Helm chart broken
   - Heavy, legacy architecture
   - Complex deployment and maintenance

### Decision Criteria

- **Kubernetes Support**: Must have native Kubernetes deployment options
- **Lightweight**: Minimal resource requirements
- **Modern Architecture**: Cloud-native, REST API based
- **Active Development**: Under active maintenance and development
- **Iceberg Focus**: Designed specifically for Iceberg (not adapted)

## Decision

**Selected Solution**: Apache Polaris

**Rationale**:
1. Purpose-built for Apache Iceberg
2. Implements standard Iceberg REST API
3. Lightweight and cloud-native
4. Active Apache incubation project
5. Simplifies deployment compared to Hive

## Implementation Plan

### Migration Strategy
Complete replacement - no data migration needed:
1. Remove all Hive Metastore components
2. Deploy Apache Polaris fresh
3. Update documentation and references
4. Validate with new Iceberg tables

### Key Changes
- Replace `/kubernetes/apps/data-platform/hive-metastore/` with `/kubernetes/apps/data-platform/polaris/`
- Update all documentation references
- Create new validation scripts for Polaris
- Modify data platform objectives

## Documentation Created

1. **Migration Plan**: `/docs/data-platform/hive-to-polaris-migration.md`
   - Comprehensive migration strategy
   - File inventory for changes
   - Implementation details
   - Testing procedures

2. **Updated Objectives**: Data Platform Phase 1 now targets Polaris instead of Hive

## Lessons Learned

1. **Vendor Lock-in**: Relying on single-maintainer Helm charts (GetInData) creates risk
2. **Modern vs Legacy**: Cloud-native solutions (Polaris) are simpler than adapted legacy (Hive)
3. **Investigation Value**: Thorough investigation of alternatives prevented future issues
4. **REST API Standard**: Choosing standards-based solutions provides flexibility

## Impact on Data Platform

- **Simplified Architecture**: Removed complex Hive dependencies
- **Modern Stack**: Aligns with cloud-native principles
- **Future Features**: Enables full Iceberg feature set via REST API
- **Reduced Maintenance**: Lighter solution with fewer moving parts

## Next Steps

1. Execute Phase 1 of migration plan (Hive removal)
2. Deploy Apache Polaris using official Helm charts
3. Update all documentation and scripts
4. Validate Iceberg integration
5. Continue with Phase 1 objectives (Iceberg tables, backups)

## References

- [Migration Plan](/docs/data-platform/hive-to-polaris-migration.md)
- [Apache Polaris GitHub](https://github.com/apache/polaris)
- [Original Issue](https://github.com/getindata/hive-metastore/issues) (Helm chart bug)

## Success Metrics

- ✅ Identified critical blocker in Hive deployment
- ✅ Investigated 4 alternative solutions
- ✅ Made architectural decision based on evidence
- ✅ Created comprehensive migration plan
- ✅ Documented decision and rationale