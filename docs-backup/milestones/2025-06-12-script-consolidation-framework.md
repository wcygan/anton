# Milestone: Script Consolidation Framework

**Date**: 2025-06-12  
**Category**: Infrastructure  
**Status**: Planned

## Summary

Consolidate and standardize the 98 Deno TypeScript scripts to eliminate code duplication, create shared utilities, and establish a unified CLI framework for homelab operations.

## Goals

- [ ] Create shared KubectlExecutor utility to eliminate duplicate kubectl execution code
- [ ] Implement BaseMonitor framework for standardized monitoring interfaces
- [ ] Establish centralized logging and error handling patterns
- [ ] Expand CLI framework to cover all operational tasks
- [ ] Standardize JSON output schemas across all monitoring scripts
- [ ] Create plugin architecture for extensible functionality

## Implementation Details

### Components to Refactor
- KubectlExecutor utility (eliminates duplication in 15+ scripts)
- BaseMonitor framework (standardizes monitoring interfaces)
- OutputFormatter utility (unifies color/table formatting)
- ErrorHandler utility (consistent error handling and exit codes)
- Logger utility (centralized logging with JSON support)

### Configuration Changes
- Create scripts/lib/ directory for shared utilities
- Establish consistent CLI argument parsing patterns
- Standardize monitoring result schemas
- Implement parallel execution patterns consistently

## Validation

### Tests Performed
- Performance benchmarks for parallel execution
- Backward compatibility validation
- CLI interface consistency checks
- JSON schema validation

### Metrics
- Code duplication reduction: Target 40-50%
- Performance improvement: Target 3-5x for monitoring operations
- Script count in lib/: Target 6-8 shared utilities
- CLI command coverage: Target 100% of current script functionality

## Lessons Learned

### What Went Well
- Current parallel execution patterns show 5x performance gains
- JSON output standardization enables automation
- Deno ecosystem provides excellent tooling support

### Challenges
- Balancing abstraction vs. flexibility
- Maintaining backward compatibility during migration
- Coordinating changes across 98 files

## Next Steps

- Phase 1: Create KubectlExecutor and BaseMonitor utilities
- Phase 2: Migrate core monitoring scripts to new framework
- Phase 3: Expand CLI framework for all operational tasks
- Phase 4: Implement caching and performance optimizations

## References

- [Current script analysis](../investigations/2025-06-12-refactoring-analysis.md)
- [Deno performance patterns](https://deno.land/manual/runtime/performance)
- [CLI framework design](scripts/cli/homelab.ts)