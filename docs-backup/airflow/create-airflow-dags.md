# Create Airflow DAGs

I am new to Airflow, so I am going to create a simple DAG to test the waters.

## Example 1: Hello World Hourly

This DAG will print "Hello World!" to the console every hour.

### DAG Configuration

1. **Enable GitSync**: We've configured Airflow to sync DAGs from a Git
   repository. The `HelmRelease` for Airflow (typically at
   `kubernetes/apps/airflow/airflow/app/helmrelease.yaml`) has been updated to
   include a `dags.gitSync` section. This points to the
   `kubernetes/apps/airflow/airflow/dags/` directory within your Git repository.

   ```yaml
   # In your helmrelease.yaml values:
   dags:
     gitSync:
       enabled: true
       repo: "https://github.com/wcygan/anton.git" # Or your repo URL
       branch: "main" # Or your default branch
       subPath: "kubernetes/apps/airflow/airflow/dags"
       syncInterval: 60 # Sync every 60 seconds
       # ... other gitSync settings (resources, private repo credentials if needed)
   ```

2. **Create the DAG file**: Create a Python file named `hello_world_dag.py` in
   the `kubernetes/apps/airflow/airflow/dags/` directory with the following
   content:

   ```python
   from __future__ import annotations

   import pendulum

   from airflow.models.dag import DAG
   from airflow.operators.bash import BashOperator

   with DAG(
       dag_id="hello_world",
       schedule="0 * * * *",  # Run hourly at the beginning of the hour
       start_date=pendulum.datetime(2023, 1, 1, tz="UTC"), # Adjust start_date as needed
       catchup=False,
       tags=["example"],
   ) as dag:
       hello_operator = BashOperator(
           task_id="say_hello",
           bash_command='echo "Hello World!"',
       )
   ```

### Deployment

1. Commit and push these changes (the `helmrelease.yaml` update and the new
   `hello_world_dag.py` file) to your Git repository.
2. Flux will automatically sync these changes to your Kubernetes cluster.
3. Airflow's `git-sync` sidecar will pull the new DAG file into the scheduler
   and webserver.
4. You should see the `hello_world` DAG appear in the Airflow UI shortly. It
   will trigger automatically every hour.

### Verification

1. Access your Airflow UI (refer to `docs/install-airflow.md` for
   port-forwarding instructions if needed).
2. Navigate to the DAGs list. You should see the `hello_world` DAG.
3. You can manually trigger it or wait for its scheduled run.
4. Check the logs for the `say_hello` task to see the "Hello World!" output.
