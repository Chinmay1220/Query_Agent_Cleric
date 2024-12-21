#imports
import os
import json
import openai
from kubernetes import client, config
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import logging
from datetime import datetime, timezone


# Set up logs
LOG_FILE = "agent.log"
logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format="%(asctime)s - %(message)s")

#fast api
app = FastAPI()
#Pydantic model for user query
class UserQuery(BaseModel):
    query: str

#fnt for gathering the kubernetes data
def gather_kubernetes_data():
    try:    
        #load from ~/.kube/config
        config.load_kube_config()

        # Initialize Kubernetes API clients
        core_api = client.CoreV1Api()
        apps_api = client.AppsV1Api()
        batch_api = client.BatchV1Api()
        networking_api = client.NetworkingV1Api()  # For Network Policies and Ingresses
        apiextensions_api = client.ApiextensionsV1Api()  # For CRDs

        cluster_info = {}

        # Cluster Info (API resources available)
        cluster_info["cluster_info"] = [
            {"name": resource.name, "kind": resource.kind} 
            for resource in core_api.get_api_resources().resources
        ]

        # Deployments
        deployments = apps_api.list_deployment_for_all_namespaces()
        cluster_info["deployments"] = [
        {
        "name": dep.metadata.name,
        "namespace": dep.metadata.namespace,
        "replicas": dep.spec.replicas,
        "type": [c.image.split(":")[0] for c in dep.spec.template.spec.containers],  # Container image name as type
        "port": [
            p.container_port for c in dep.spec.template.spec.containers if c.ports for p in c.ports
        ],
        "age": str(datetime.now(timezone.utc) - dep.metadata.creation_timestamp).split(".")[0],  # Human-readable age
        }
             for dep in deployments.items
        ]
        
        # Pods
        pods = core_api.list_pod_for_all_namespaces()
        cluster_info["pods"] = [
            {
                "name": pod.metadata.name,
                "namespace": pod.metadata.namespace,
                "containers": [c.name for c in pod.spec.containers],
                "status": pod.status.phase,
                "age": str(
            datetime.now(timezone.utc) - pod.metadata.creation_timestamp
        ).split(".")[0],  # Convert timedelta to a human-readable string
    
            }
            for pod in pods.items
        ]


        # Nodes
        nodes = core_api.list_node()
        cluster_info["nodes"] = [
            {
                "name": node.metadata.name,
                "status": node.status.conditions[-1].type,
                "addresses": [addr.address for addr in node.status.addresses],
                "roles": ",".join(
                [label.split("/")[-1] for label in node.metadata.labels.keys() if "role" in label]
                ) or "None",  # Extract roles based on labels
                "age": str(datetime.now(timezone.utc) - node.metadata.creation_timestamp).split(".")[0],  # Node age
                "version": node.status.node_info.kubelet_version,  # Kubernetes version on the node
    
            }
            for node in nodes.items
        ]

        # ReplicaSets
        replicasets = apps_api.list_replica_set_for_all_namespaces()
        cluster_info["replicasets"] = [
            {
                "name": rs.metadata.name,
                "namespace": rs.metadata.namespace,
                "replicas": rs.spec.replicas,
                "available_replicas": rs.status.available_replicas or 0,  # Default to 0 if not set
                "ready_replicas": rs.status.ready_replicas or 0,  # Default to 0 if not set
                "age": str(datetime.now(timezone.utc) - rs.metadata.creation_timestamp).split(".")[0],  # Human-readable age
                "labels": rs.metadata.labels or {},  # Include labels
                "selector": rs.spec.selector.match_labels or {},  # Label selector
                "owner": rs.metadata.owner_references[0].name if rs.metadata.owner_references else "None",  # Owner (Deployment)
            }
            for rs in replicasets.items
        ]

        # Persistent Volumes (PVs)
        pv_api = client.CoreV1Api()
        pvs = pv_api.list_persistent_volume()
        cluster_info["pvs"] = [
            {
                "name": pv.metadata.name,
                "status": pv.status.phase,
                "capacity": pv.spec.capacity["storage"],  # Storage capacity (e.g., 10Gi)
                "storage_class": pv.spec.storage_class_name,  # Storage class name
                "reclaim_policy": pv.spec.persistent_volume_reclaim_policy,  # Reclaim policy
                "access_modes": pv.spec.access_modes,  # List of access modes
                "volume_mode": pv.spec.volume_mode or "Filesystem",  # Volume mode (default to Filesystem)
                "claim": pv.spec.claim_ref.name if pv.spec.claim_ref else "Unbound",  # Bound PVC name or Unbound
                "age": str(datetime.now(timezone.utc) - pv.metadata.creation_timestamp).split(".")[0],  # Human-readable age
        }   
            for pv in pvs.items
        ]

         # Secrets
        secrets = core_api.list_secret_for_all_namespaces()
        cluster_info["secrets"] = [
            {"name": secret.metadata.name, "namespace": secret.metadata.namespace}
            for secret in secrets.items
        ]

        # Horizontal Pod Autoscalers (HPAs)
        hpa_api = client.AutoscalingV1Api()
        hpas = hpa_api.list_horizontal_pod_autoscaler_for_all_namespaces()
        cluster_info["hpas"] = [
            {
                "name": hpa.metadata.name,
                "namespace": hpa.metadata.namespace,
                "min_replicas": hpa.spec.min_replicas,
                "max_replicas": hpa.spec.max_replicas,
            }
            for hpa in hpas.items
        ]

        # ConfigMaps
        configmaps = core_api.list_config_map_for_all_namespaces()
        cluster_info["configmaps"] = [
            {"name": cm.metadata.name, "namespace": cm.metadata.namespace}
            for cm in configmaps.items
        ]

        # CronJobs
        cronjobs = batch_api.list_cron_job_for_all_namespaces()
        cluster_info["cronjobs"] = [
            {
                "name": cronjob.metadata.name,
                "namespace": cronjob.metadata.namespace,
                "schedule": cronjob.spec.schedule,
            }
            for cronjob in cronjobs.items
        ]


        # Resource Quotas
        resource_quotas = core_api.list_resource_quota_for_all_namespaces()
        cluster_info["resource_quotas"] = [
            {
                "name": rq.metadata.name,
                "namespace": rq.metadata.namespace,
                "hard": rq.spec.hard,
            }
            for rq in resource_quotas.items
        ]

        # Events
        events_api = core_api.list_event_for_all_namespaces()
        cluster_info["events"] = [
            {
                "name": event.metadata.name,
                "namespace": event.metadata.namespace,
                "message": event.message,
                "reason": event.reason,
                "type": event.type,
            }
            for event in events_api.items
        ]

        # Network Policies
        network_policies = networking_api.list_network_policy_for_all_namespaces()
        cluster_info["network_policies"] = [
            {
                "name": np.metadata.name,
                "namespace": np.metadata.namespace,
            }
            for np in network_policies.items
        ]   

        # Custom Resource Definitions (CRDs)
        crds = apiextensions_api.list_custom_resource_definition()
        cluster_info["crds"] = [
            {"name": crd.metadata.name} for crd in crds.items
        ]

        # StatefulSets
        statefulsets = apps_api.list_stateful_set_for_all_namespaces()
        cluster_info["statefulsets"] = [
            {
                "name": ss.metadata.name,
                "namespace": ss.metadata.namespace,
                "replicas": ss.spec.replicas,
            }
            for ss in statefulsets.items
        ]

        # Ingresses
        ingresses = networking_api.list_ingress_for_all_namespaces()
        cluster_info["ingresses"] = [
            {
                "name": ingress.metadata.name,
                "namespace": ingress.metadata.namespace,
                "host": ingress.spec.rules[0].host if ingress.spec.rules else "N/A",
            }
            for ingress in ingresses.items
        ]

        # Kubeconfig Details (read config file content)
        kubeconfig_path = os.path.expanduser("~/.kube/config")
        with open(kubeconfig_path) as kube_config_file:
            cluster_info["kubeconfig"] = kube_config_file.read()

        # Current Context
        cluster_info["current_context"] = config.list_kube_config_contexts()[1]

        # All Contexts
        cluster_info["all_contexts"] = [
            context["name"] for context in config.list_kube_config_contexts()[0]
        ]

        # Log and print the gathered data
        # print("\n--- Gathered Kubernetes Cluster Information ---")
        # print(json.dumps(cluster_info, indent=2))

        return cluster_info
    
    except Exception as e:
        raise Exception(f"Error gathering Kubernetes information: {e}")
    
#fnt to send the data to gpt model
def query_llm(cluster_data, user_query):
    try:
        # Construct the prompt with both gathered Kubernetes data and the user query
        prompt = f"""
        You are an expert Kubernetes assistant. Given the following information about a Kubernetes cluster:

        {json.dumps(cluster_data, indent=2)}

        Answer the following query related to Kubernetes. If the query is not relevant to Kubernetes or the provided information, respond with: "I don't have that information.".

        Query: {user_query}
        """

# Set your OpenAI API key here
        openai.api_key = 'OPENAI_API_KEY'

# Send the prompt to GPT-4 using the v1/chat/completions endpoint
        response = openai.ChatCompletion.create(
            model="gpt-4",  # Use the chat model, such as GPT-4 or GPT-3.5-turbo
            messages=[{"role": "system", "content": "You are a helpful assistant."},
                      {"role": "user", "content": prompt}],
            max_tokens=150,
            temperature=0.5
        )

        # Extract and return the answer from the LLM's response
        return response.choices[0].message["content"].strip()

    except Exception as e:
        raise Exception(f"Error querying the LLM: {e}")

#fastapi endpoint

@app.post("/query/")
async def query_kubernetes(query: UserQuery):
    try:
        # Gather Kubernetes cluster data
        cluster_data = gather_kubernetes_data()

        # Get the user query
        user_query = query.query

        # Query the LLM with the gathered data and user query
        answer = query_llm(cluster_data, user_query)

        # Log the query and the answer to the log file
        logging.info(f"User Query: {user_query}")
        logging.info(f"Agent Answer: {answer}")

        # Return the answer as JSON response
        return {"answer": answer}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



