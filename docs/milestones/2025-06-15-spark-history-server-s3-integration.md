# Milestone: Spark History Server S3 Integration

**Date**: 2025-06-15  
**Category**: Infrastructure  
**Status**: Complete

## Summary

Successfully deployed and configured Apache Spark History Server with S3 integration for the data platform. Resolved critical issues with missing S3 libraries in the Apache Spark image by implementing an init container solution. Created integration tests to validate the entire event logging pipeline from Spark jobs to History Server visualization.

## Goals

- [x] Deploy Spark History Server with S3 event log storage
- [x] Fix S3 connectivity issues with Apache Spark image
- [x] Create iceberg-test S3 bucket for event logs
- [x] Implement integration tests for validation
- [x] Verify end-to-end functionality

## Implementation Details

### Components Deployed
- Apache Spark History Server (apache/spark:3.5.3)
- Init container for S3 library downloads
- S3 bucket creation job
- Integration test scripts

### Configuration Changes
- **Init Container Pattern**: Added init container to download hadoop-aws (3.3.4) and aws-java-sdk-bundle (1.12.367) JARs
- **Environment Variables**: Configured AWS credentials from Rook-Ceph secrets
- **S3 Configuration**: Set up proper endpoints for Ceph RadosGW compatibility
- **Spark Configuration**: Added S3A filesystem settings for event logging
- **Deployment Fix**: Switched from multiple failed images (Bitnami, Lightbend, bde2020) to Apache Spark with init container

## Validation

### Tests Performed
- **S3 Bucket Creation**: Successfully created iceberg-test bucket with spark-events directory
- **Spark Job Execution**: Ran Spark Pi job with event logging enabled - completed in 3.6 seconds
- **Event Log Writing**: Verified logs written to s3a://iceberg-test/spark-events/
- **History Server API**: Confirmed API endpoint returns job listings at /api/v1/applications
- **Integration Test**: Created test-spark-s3-simple.ts for automated validation

### Metrics
- **Spark History Server Pod**: 1/1 Ready
- **Event Logs in S3**: 2 jobs successfully logged
- **API Response Time**: < 100ms
- **Job Completion Time**: ~3.5 seconds for Spark Pi with 100 iterations
- **S3 Storage Used**: 377KB per job event log

## Lessons Learned

### What Went Well
- **Init Container Pattern**: Clean solution for adding runtime dependencies
- **S3 Integration**: Rook-Ceph S3 worked seamlessly once configured
- **Monitoring Integration**: History Server provides excellent visibility into Spark jobs
- **API Access**: RESTful API enables programmatic job monitoring

### Challenges
- **Missing S3 Libraries**: Apache Spark image lacks hadoop-aws and aws-java-sdk-bundle JARs
  - Resolution: Init container downloads JARs at runtime
- **Image Selection**: Multiple popular images (Bitnami, Lightbend) had various issues
  - Resolution: Stuck with official Apache image + customization
- **Authentication Errors**: Bitnami image had Unix login module issues with non-root user
  - Resolution: Avoided by using Apache Spark image
- **Spark Operator Issues**: SparkApplications not being processed in data-platform namespace
  - Status: Separate issue, needs investigation

## Next Steps

### Immediate
- Fix Spark Operator namespace watching configuration
- Enable SparkApplication CRD processing
- Add Prometheus metrics scraping for History Server

### Short-term
- Configure ingress for external History Server access
- Set up event log retention policies
- Create Grafana dashboards for Spark job metrics
- Document Spark job submission procedures

### Long-term
- Implement automated performance testing
- Add job failure alerting
- Create runbooks for common Spark issues
- Integrate with data platform monitoring stack

## References

- [Spark History Server Configuration](../../kubernetes/apps/data-platform/spark-applications/app/monitoring/spark-history-server.yaml)
- [Integration Test Script](../../scripts/test-spark-s3-simple.ts)
- [S3 Bucket Creation Job](../../tmp/create-bucket-simple.yaml)
- [Apache Spark Event Logging Docs](https://spark.apache.org/docs/latest/monitoring.html#viewing-after-the-fact)
- [Commit: feat(spark): add integration test for Spark History Server](https://github.com/wcygan/homelab/commit/2c2244a)