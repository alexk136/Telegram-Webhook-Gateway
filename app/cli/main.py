from __future__ import annotations

import argparse
import asyncio
import json
import logging

from app.cli.api_client import (
    AuthorizationError,
    ClientConfigError,
    GatewayApiClientError,
    PullApiClient,
    TemporaryNetworkError,
)
from app.cli.commands.pull_once import run_pull_once_command
from app.cli.config import CLIConfig, load_cli_config
from app.cli.poller import PullBridgePoller


logger = logging.getLogger("tgw-cli")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Telegram Webhook Gateway CLI consumer")
    parser.add_argument("--server-base-url", "--base-url", dest="server_base_url", default=None, help="Gateway base URL")
    parser.add_argument("--token", dest="pull_api_token", default=None, help="Pull API bearer token")
    parser.add_argument("--bot-id", dest="bot_id", default=None, help="Bot ID for pull requests")
    parser.add_argument("--consumer-id", dest="consumer_id", default=None, help="Consumer ID")
    parser.add_argument("--batch-size", "--pull-limit", dest="batch_size", type=int, default=None, help="Pull batch size")
    parser.add_argument("--lease-seconds", dest="lease_seconds", type=int, default=None, help="Lease duration")
    parser.add_argument(
        "--request-timeout-sec",
        dest="request_timeout_sec",
        type=float,
        default=None,
        help="HTTP timeout for gateway/local webhook calls",
    )
    parser.add_argument(
        "--error-backoff-initial-sec",
        dest="error_backoff_initial_sec",
        type=float,
        default=None,
        help="Initial error backoff delay for poll loop",
    )
    parser.add_argument(
        "--error-backoff-max-sec",
        dest="error_backoff_max_sec",
        type=float,
        default=None,
        help="Maximum error backoff delay for poll loop",
    )
    parser.add_argument(
        "--error-backoff-multiplier",
        dest="error_backoff_multiplier",
        type=float,
        default=None,
        help="Backoff multiplier for repeated errors in poll loop",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    pull_once_parser = subparsers.add_parser("pull-once", help="Pull one batch and print summary")
    pull_once_parser.add_argument(
        "--forward",
        action="store_true",
        help="Forward pulled messages to LOCAL_WEBHOOK_URL instead of printing only",
    )

    stats_parser = subparsers.add_parser("stats", help="Show pull queue stats")
    stats_parser.add_argument("--stats-bot-id", dest="stats_bot_id", default=None, help="Optional stats bot filter")

    poll_parser = subparsers.add_parser("poll", help="Run polling loop")
    poll_parser.add_argument(
        "--iterations",
        type=int,
        default=0,
        help="Number of poll iterations. Default 0 means infinite loop.",
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

    return parser


async def run_pull_once(*, cfg: CLIConfig, api_client: PullApiClient) -> int:
    return await run_pull_once_command(cfg=cfg, api_client=api_client, forward=False)


async def run_stats(*, api_client: PullApiClient, stats_bot_id: str | None) -> int:
    data = await api_client.pull_stats(bot_id=stats_bot_id)
    print(json.dumps(data))
    return 0


async def run_poll(*, cfg: CLIConfig, api_client: PullApiClient, iterations: int) -> int:
    if not cfg.local_webhook_url:
        raise ValueError("LOCAL_WEBHOOK_URL is required for poll command")
    if iterations < 0:
        raise ValueError("--iterations must be >= 0")

    poller = PullBridgePoller(
        api_client=api_client,
        local_webhook_url=cfg.local_webhook_url,
        consumer_id=cfg.consumer_id,
        local_timeout_sec=cfg.request_timeout_sec,
    )
    logger.info(
        "poll started: bot_id=%s consumer_id=%s batch_size=%s lease_seconds=%s interval_sec=%s iterations=%s backoff_initial=%s backoff_max=%s backoff_multiplier=%s",
        cfg.bot_id,
        cfg.consumer_id,
        cfg.batch_size,
        cfg.lease_seconds,
        cfg.poll_interval_sec,
        iterations,
        cfg.error_backoff_initial_sec,
        cfg.error_backoff_max_sec,
        cfg.error_backoff_multiplier,
    )

    current = 0
    current_backoff = cfg.error_backoff_initial_sec
    while True:
        sleep_delay = cfg.poll_interval_sec
        try:
            items = await api_client.pull_updates(
                bot_id=cfg.bot_id,
                consumer_id=cfg.consumer_id,
                limit=cfg.batch_size,
                lease_seconds=cfg.lease_seconds,
            )
            if not items:
                logger.info("poll iteration=%s: no messages", current + 1)
            else:
                logger.info("poll iteration=%s: pulled=%s", current + 1, len(items))
                await poller.process_batch(items)
            current_backoff = cfg.error_backoff_initial_sec
        except AuthorizationError as exc:
            sleep_delay = current_backoff
            logger.error("poll iteration=%s pull_api_auth_error=%s", current + 1, exc)
            logger.warning("backoff_applied delay_sec=%s", sleep_delay)
            current_backoff = min(
                cfg.error_backoff_max_sec,
                current_backoff * cfg.error_backoff_multiplier,
            )
        except TemporaryNetworkError as exc:
            sleep_delay = current_backoff
            logger.warning("poll iteration=%s temporary network error: %s", current + 1, exc)
            logger.warning("backoff_applied delay_sec=%s", sleep_delay)
            current_backoff = min(
                cfg.error_backoff_max_sec,
                current_backoff * cfg.error_backoff_multiplier,
            )
        except GatewayApiClientError as exc:
            sleep_delay = current_backoff
            logger.error("poll iteration=%s gateway api error: %s", current + 1, exc)
            logger.warning("backoff_applied delay_sec=%s", sleep_delay)
            current_backoff = min(
                cfg.error_backoff_max_sec,
                current_backoff * cfg.error_backoff_multiplier,
            )
        except Exception:
            sleep_delay = current_backoff
            logger.exception("poll iteration=%s unexpected error", current + 1)
            logger.warning("backoff_applied delay_sec=%s", sleep_delay)
            current_backoff = min(
                cfg.error_backoff_max_sec,
                current_backoff * cfg.error_backoff_multiplier,
            )

        current += 1
        if iterations > 0 and current >= iterations:
            break
        await asyncio.sleep(sleep_delay)

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
        server_base_url=args.server_base_url,
        pull_api_token=args.pull_api_token,
        bot_id=args.bot_id,
        consumer_id=args.consumer_id,
        batch_size=args.batch_size,
        lease_seconds=args.lease_seconds,
        poll_interval_sec=getattr(args, "poll_interval_sec", None),
        local_webhook_url=getattr(args, "local_webhook_url", None),
        request_timeout_sec=args.request_timeout_sec,
        error_backoff_initial_sec=args.error_backoff_initial_sec,
        error_backoff_max_sec=args.error_backoff_max_sec,
        error_backoff_multiplier=args.error_backoff_multiplier,
        require_local_webhook=args.command == "poll" or (
            args.command == "pull-once" and bool(getattr(args, "forward", False))
        ),
    )
    logger.info("CLI config: %s", cfg.masked_dict())

    api_client = PullApiClient(
        base_url=cfg.server_base_url,
        pull_api_token=cfg.pull_api_token,
        timeout_sec=cfg.request_timeout_sec,
    )
    try:
        if args.command == "pull-once":
            return await run_pull_once_command(
                cfg=cfg,
                api_client=api_client,
                forward=bool(getattr(args, "forward", False)),
            )
        if args.command == "stats":
            return await run_stats(api_client=api_client, stats_bot_id=args.stats_bot_id)
        if args.command == "poll":
            return await run_poll(cfg=cfg, api_client=api_client, iterations=args.iterations)
        raise RuntimeError(f"Unknown command: {args.command}")
    finally:
        await api_client.close()


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO)
    try:
        return asyncio.run(_main_async(argv))
    except KeyboardInterrupt:
        logger.info("Interrupted")
        return 130
    except (ValueError, ClientConfigError) as exc:
        logger.error("Configuration error: %s", exc)
        return 2
    except AuthorizationError as exc:
        logger.error("Authorization error: %s", exc)
        return 3
    except TemporaryNetworkError as exc:
        logger.error("Temporary network error: %s", exc)
        return 4
    except GatewayApiClientError as exc:
        logger.error("Gateway API error: %s", exc)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
