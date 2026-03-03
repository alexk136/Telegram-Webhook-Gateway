from __future__ import annotations

import argparse
import asyncio
import json
import logging

from app.cli.api_client import PullApiClient
from app.cli.config import CLIConfig, load_cli_config
from app.cli.poller import PullBridgePoller


logger = logging.getLogger("tgw-cli")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Telegram Webhook Gateway CLI consumer")
    parser.add_argument("--base-url", dest="base_url", default=None, help="Gateway base URL")
    parser.add_argument("--token", dest="pull_api_token", default=None, help="Pull API bearer token")
    parser.add_argument("--bot-id", dest="bot_id", default=None, help="Bot ID for pull requests")
    parser.add_argument("--consumer-id", dest="consumer_id", default=None, help="Consumer ID")
    parser.add_argument("--pull-limit", dest="pull_limit", type=int, default=None, help="Pull batch size")
    parser.add_argument("--lease-seconds", dest="lease_seconds", type=int, default=None, help="Lease duration")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("pull-once", help="Pull one batch and print summary")

    stats_parser = subparsers.add_parser("stats", help="Show pull queue stats")
    stats_parser.add_argument("--stats-bot-id", dest="stats_bot_id", default=None, help="Optional stats bot filter")

    poll_parser = subparsers.add_parser("poll", help="Run polling loop")
    poll_parser.add_argument(
        "--iterations",
        type=int,
        default=1,
        help="Number of poll iterations. Use 0 for infinite loop.",
    )
    poll_parser.add_argument(
        "--poll-interval-sec",
        dest="poll_interval_sec",
        type=float,
        default=None,
        help="Sleep interval between poll iterations",
    )
    poll_parser.add_argument(
        "--local-webhook-url",
        dest="local_webhook_url",
        default=None,
        help="Local webhook URL for forwarding",
    )
    poll_parser.add_argument(
        "--local-timeout-sec",
        dest="local_timeout_sec",
        type=float,
        default=None,
        help="Local webhook HTTP timeout",
    )

    return parser


async def run_pull_once(*, cfg: CLIConfig, api_client: PullApiClient) -> int:
    items = await api_client.pull_updates(
        bot_id=cfg.bot_id,
        consumer_id=cfg.consumer_id,
        limit=cfg.pull_limit,
        lease_seconds=cfg.lease_seconds,
    )
    print(json.dumps({"command": "pull-once", "count": len(items)}))
    return 0


async def run_stats(*, api_client: PullApiClient, stats_bot_id: str | None) -> int:
    data = await api_client.pull_stats(bot_id=stats_bot_id)
    print(json.dumps(data))
    return 0


async def run_poll(*, cfg: CLIConfig, api_client: PullApiClient, iterations: int) -> int:
    poller = PullBridgePoller(
        api_client=api_client,
        local_webhook_url=cfg.local_webhook_url,
        consumer_id=cfg.consumer_id,
        local_timeout_sec=cfg.local_timeout_sec,
    )

    current = 0
    while True:
        items = await api_client.pull_updates(
            bot_id=cfg.bot_id,
            consumer_id=cfg.consumer_id,
            limit=cfg.pull_limit,
            lease_seconds=cfg.lease_seconds,
        )
        if items:
            await poller.process_batch(items)

        current += 1
        if iterations > 0 and current >= iterations:
            break
        await asyncio.sleep(cfg.poll_interval_sec)

    print(
        json.dumps(
            {
                "command": "poll",
                "iterations": current,
                "counters": poller.counters.__dict__,
            }
        )
    )
    return 0


async def _main_async(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    cfg = load_cli_config(
        gateway_base_url=args.base_url,
        pull_api_token=args.pull_api_token,
        bot_id=args.bot_id,
        consumer_id=args.consumer_id,
        pull_limit=args.pull_limit,
        lease_seconds=args.lease_seconds,
        poll_interval_sec=getattr(args, "poll_interval_sec", None),
        local_webhook_url=getattr(args, "local_webhook_url", None),
        local_timeout_sec=getattr(args, "local_timeout_sec", None),
    )

    api_client = PullApiClient(
        base_url=cfg.gateway_base_url,
        pull_api_token=cfg.pull_api_token,
    )
    try:
        if args.command == "pull-once":
            return await run_pull_once(cfg=cfg, api_client=api_client)
        if args.command == "stats":
            return await run_stats(api_client=api_client, stats_bot_id=args.stats_bot_id)
        if args.command == "poll":
            return await run_poll(cfg=cfg, api_client=api_client, iterations=args.iterations)
        raise RuntimeError(f"Unknown command: {args.command}")
    finally:
        await api_client.close()


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO)
    return asyncio.run(_main_async(argv))


if __name__ == "__main__":
    raise SystemExit(main())
