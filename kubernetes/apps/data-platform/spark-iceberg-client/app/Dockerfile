# Spark with Iceberg Dependencies
# This image pre-builds all required JAR dependencies to eliminate runtime downloads
FROM apache/spark:3.5.5-scala2.12-java11-python3-ubuntu

# Switch to root user to install dependencies
USER root

# Download and install Iceberg dependencies
WORKDIR /opt/spark/jars

# Iceberg Spark runtime for Spark 3.5
RUN curl -L -o iceberg-spark-runtime-3.5_2.12-1.5.2.jar \
    https://repo1.maven.org/maven2/org/apache/iceberg/iceberg-spark-runtime-3.5_2.12/1.5.2/iceberg-spark-runtime-3.5_2.12-1.5.2.jar

# Nessie Spark SQL extension
RUN curl -L -o nessie-spark-extensions-3.5_2.12-0.77.1.jar \
    https://repo1.maven.org/maven2/org/projectnessie/nessie-integrations/nessie-spark-extensions-3.5_2.12/0.77.1/nessie-spark-extensions-3.5_2.12-0.77.1.jar

# AWS S3 support for Hadoop
RUN curl -L -o hadoop-aws-3.3.4.jar \
    https://repo1.maven.org/maven2/org/apache/hadoop/hadoop-aws/3.3.4/hadoop-aws-3.3.4.jar

# AWS Java SDK
RUN curl -L -o aws-java-sdk-bundle-1.12.367.jar \
    https://repo1.maven.org/maven2/com/amazonaws/aws-java-sdk-bundle/1.12.367/aws-java-sdk-bundle-1.12.367.jar

# Verify all JARs were downloaded
RUN ls -la /opt/spark/jars/ | grep -E "(iceberg|nessie|hadoop-aws|aws-java-sdk)"

# Set proper permissions
RUN chmod 644 /opt/spark/jars/*.jar && \
    chown -R spark:spark /opt/spark/jars/

# Switch back to spark user
USER spark

# Set working directory
WORKDIR /opt/spark

# Health check to ensure Spark can start
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD $SPARK_HOME/bin/spark-shell --version || exit 1

# Default command
CMD ["sleep", "infinity"]