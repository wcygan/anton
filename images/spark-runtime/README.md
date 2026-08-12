# Immutable Spark runtime

Build this image from the repository root.

```sh
docker build --file images/spark-runtime/Dockerfile --tag spark-runtime:4.1.3 .
docker run --rm spark-runtime:4.1.3 python3 /opt/spark/runtime-contract/verify-runtime.py
```

The build creates these evidence files in the final image:

- `/opt/spark/runtime-contract/dependency-tree.txt`
- `/opt/spark/runtime-contract/jar-inventory.json`
- `/opt/spark/runtime-contract/aws-sdk-classes.json`
- `/opt/spark/runtime-contract/effective-versions.json`

Run the SeaweedFS checks only with approved credentials and endpoints.

```sh
docker run --rm \
  --env ICEBERG_CATALOG_URI \
  --env S3_ENDPOINT \
  --env AWS_ACCESS_KEY_ID \
  --env AWS_SECRET_ACCESS_KEY \
  --env ICEBERG_WAREHOUSE=s3://iceberg-shadow \
  spark-runtime:4.1.3 \
  python3 /opt/spark/runtime-contract/verify-runtime.py --storage
```

The storage check writes one uniquely named Iceberg table and one temporary
S3A object. It deletes the S3A object. Retain command output and image digest
with the qualification evidence.
