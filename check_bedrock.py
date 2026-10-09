"""T1 acceptance check: one Bedrock call that returns text.

Uses the Converse API (the same path Strands' BedrockModel uses), so if this
works the agent layer in T7 will be able to reach the model too.

    python check_bedrock.py
"""

import os
import sys

import boto3
from botocore.exceptions import ClientError, NoCredentialsError, ProfileNotFound
from dotenv import load_dotenv


def list_claude_ids(session: boto3.Session, region: str) -> list[str]:
    """Best-effort listing of Claude model / inference-profile IDs in the region."""
    bedrock = session.client("bedrock", region_name=region)
    ids = []
    try:
        for m in bedrock.list_foundation_models(byProvider="Anthropic")["modelSummaries"]:
            ids.append(m["modelId"])
        for p in bedrock.list_inference_profiles()["inferenceProfileSummaries"]:
            if "anthropic" in p["inferenceProfileId"]:
                ids.append(p["inferenceProfileId"])
    except ClientError:
        pass
    return ids


def main() -> int:
    load_dotenv()
    region = os.getenv("AWS_REGION", "us-west-2")
    model_id = os.getenv("BEDROCK_MODEL_ID")
    if not model_id:
        print("BEDROCK_MODEL_ID is not set. Copy .env.example to .env and fill it in.")
        return 1

    try:
        session = boto3.Session(profile_name=os.getenv("AWS_PROFILE") or None)
        identity = session.client("sts", region_name=region).get_caller_identity()
    except (NoCredentialsError, ProfileNotFound) as e:
        print(f"No usable AWS credentials ({e}). Run `aws configure` or `aws sso login` first.")
        return 1
    except ClientError as e:
        print(f"AWS credentials rejected: {e}")
        return 1
    print(f"AWS account {identity['Account']}  region {region}  model {model_id}")

    runtime = session.client("bedrock-runtime", region_name=region)
    try:
        resp = runtime.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": "Reply with exactly: bedrock ok"}]}],
            inferenceConfig={"maxTokens": 256},
        )
    except ClientError as e:
        code = e.response["Error"]["Code"]
        print(f"Bedrock call failed: {code}: {e.response['Error']['Message']}")
        if code in ("AccessDeniedException", "ValidationException", "ResourceNotFoundException"):
            ids = list_claude_ids(session, region)
            if ids:
                print("Claude IDs visible in this region (model access may still need enabling):")
                for i in ids:
                    print(f"  {i}")
            else:
                print("Check Bedrock console -> Model access for this region.")
        return 1

    text = "".join(b.get("text", "") for b in resp["output"]["message"]["content"])
    usage = resp.get("usage", {})
    print(f"stopReason={resp['stopReason']}  tokens in/out={usage.get('inputTokens')}/{usage.get('outputTokens')}")
    print(f"response: {text.strip()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
