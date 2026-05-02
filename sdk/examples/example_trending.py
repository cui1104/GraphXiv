"""
Example: Using trending and social impact features
"""

from deepxiv_sdk import Reader


# Example 1: Get trending papers (no token required)
print("=" * 60)
print("Example 1: Get Trending Papers")
print("=" * 60)

reader = Reader()
result = reader.trending(days=7, limit=3)

print(f"\nFound {result['total']} trending papers")
for paper in result['papers']:
    print(f"\n#{paper['rank']}: {paper['arxiv_id']}")
    print(f"  Views: {paper['stats']['total_views']}")
    print(f"  Likes: {paper['stats']['total_likes']}")


# Example 2: Get social impact metrics (requires token)
print("\n" + "=" * 60)
print("Example 2: Get Social Impact Metrics")
print("=" * 60)

YOUR_TOKEN = "your_token_here"

if YOUR_TOKEN != "your_token_here":
    reader = Reader(token=YOUR_TOKEN)
    impact = reader.social_impact("2409.05591")

    if impact:
        print(f"\nSocial Impact for 2409.05591:")
        print(f"  Views: {impact['total_views']}")
        print(f"  Tweets: {impact['total_tweets']}")
        print(f"  Likes: {impact['total_likes']}")
    else:
        print("\nNo social impact data found")
else:
    print("\nTo test this example, set YOUR_TOKEN to a valid API token")
