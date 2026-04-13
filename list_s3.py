import boto3
from app.core.config import get_settings

settings = get_settings()
s3 = boto3.client(
    "s3",
    endpoint_url=settings.s3_endpoint,
    aws_access_key_id=settings.s3_access_key.get_secret_value(),
    aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
    region_name=settings.s3_region
)

response = s3.list_objects_v2(Bucket=settings.s3_bucket, Prefix="game_data/wild_rift/champion_icons/")
for obj in response.get("Contents", [])[:5]:
    print(obj["Key"])
