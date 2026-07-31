#!/usr/bin/env python3
"""
Analyze AQLite ozone data across monitors: per-device stats, R² vs fleet mean, line graph.

Usage:
    # Single day:
    docker compose run --rm web python scripts/aqlite_analysis.py --start 2026-06-16

    # Date range:
    docker compose run --rm web python scripts/aqlite_analysis.py \
        --start 2026-06-16 --end 2026-06-18

    # Custom device list:
    docker compose run --rm web python scripts/aqlite_analysis.py \
        --start 2026-06-16 --devices 1608 1609 1610 1621

--start and --end are local calendar dates (America/Los_Angeles). --end defaults to
the day after --start, so omitting it covers one full local day. Graph is saved to
scripts/aqlite-graphs/.
"""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'camp.settings.base')
import django
django.setup()

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from django.conf import settings

from camp.apps.monitors.aqlite.models import AQLite, Organization

DEFAULT_DEVICES = ['1608', '1609', '1610', '1611', '1621']
GRAPHS_DIR = os.path.join(os.path.dirname(__file__), 'aqlite-graphs')


def parse_date(s):
    """Midnight on date s in the default local timezone, returned as UTC."""
    return datetime.strptime(s, '%Y-%m-%d').replace(tzinfo=settings.DEFAULT_TIMEZONE).astimezone(timezone.utc)


def fetch_ozone(org, device_id, start, end):
    """Return {timestamp_str: float_ppb} for one device."""
    records = org.api.get_time_series(f'AQLite-{device_id}', start, end, average=0)
    result = {}
    for rec in records:
        ts = rec.get('timestamp')
        raw = rec.get('OZONE')
        if ts is None or raw is None:
            continue
        try:
            result[ts] = float(raw)
        except (ValueError, TypeError):
            pass
    return result


def r_squared(y, y_ref):
    """Pearson r² — linear correlation between two series, always in [0, 1]."""
    if np.std(y) == 0 or np.std(y_ref) == 0:
        return float('nan')
    return float(np.corrcoef(y, y_ref)[0, 1] ** 2)


def main():
    parser = argparse.ArgumentParser(
        description='Analyze AQLite ozone data across monitors.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--start', required=True, metavar='YYYY-MM-DD',
                        help='Start date (UTC)')
    parser.add_argument('--end', default=None, metavar='YYYY-MM-DD',
                        help='End date (UTC, exclusive). Defaults to day after --start.')
    parser.add_argument('--resample', default='5min', metavar='FREQ',
                        help='Pandas resample frequency (default: 5min, e.g. 1h, 15min, 30min)')
    parser.add_argument('--min', type=float, default=None, metavar='PPB',
                        help='Drop readings below this value (e.g. 0 to remove negatives)')
    parser.add_argument('--max', type=float, default=None, metavar='PPB',
                        help='Drop readings above this value (e.g. 20 to remove spikes)')
    parser.add_argument('--devices', nargs='+', default=DEFAULT_DEVICES,
                        metavar='ID',
                        help='Serial numbers without prefix (default: all working units)')
    args = parser.parse_args()

    start = parse_date(args.start)
    end = parse_date(args.end) if args.end else start + timedelta(days=1)
    start_label = args.start
    end_label = args.end or (end - timedelta(days=1)).strftime('%Y-%m-%d')

    org = Organization.objects.filter(is_enabled=True).first()
    if not org:
        print('No enabled Organization found in the database.', file=sys.stderr)
        sys.exit(1)

    min_label = f'{args.min:+g} ppb' if args.min is not None else 'none'
    max_label = f'{args.max:+g} ppb' if args.max is not None else 'none'
    print(f'Fetching data for {len(args.devices)} devices ({start_label} → {end_label})...')
    print(f'  resample: {args.resample}  |  min: {min_label}  |  max: {max_label}\n')

    raw = {}
    for device_id in args.devices:
        print(f'  AQLite-{device_id}...', end=' ', flush=True)
        try:
            points = fetch_ozone(org, device_id, start, end)
            raw[device_id] = points
            print(f'{len(points)} points')
        except Exception as exc:
            print(f'ERROR: {exc}')
            raw[device_id] = {}

    df = pd.DataFrame(raw)
    df.index = pd.to_datetime(df.index, utc=True)
    df = df.sort_index()

    if args.min is not None:
        df[args.devices] = df[args.devices].where(df[args.devices] >= args.min)
    if args.max is not None:
        df[args.devices] = df[args.devices].where(df[args.devices] <= args.max)

    df = df.resample(args.resample).mean()

    present = [d for d in args.devices if d in df.columns and not df[d].dropna().empty]
    if not present:
        print('\nNo data found for any device.', file=sys.stderr)
        sys.exit(1)

    df['_fleet_mean'] = df[present].mean(axis=1)

    print()
    col_w = 14
    header = f'{"Device":<{col_w}} {"Min":>8} {"Max":>8} {"Mean":>8} {"R²":>8} {"N":>6}'
    print(header)
    print('-' * len(header))

    for device_id in args.devices:
        col = df[device_id].dropna() if device_id in df.columns else pd.Series(dtype=float)
        if col.empty:
            print(f'AQLite-{device_id:<{col_w - 7}}  (no data)')
            continue
        others = [d for d in present if d != device_id]
        loo_mean = df[others].mean(axis=1)
        aligned = pd.concat([df[device_id], loo_mean], axis=1).dropna()
        r2 = (r_squared(aligned.iloc[:, 0].values, aligned.iloc[:, 1].values)
              if len(aligned) > 1 else float('nan'))
        print(
            f'AQLite-{device_id:<{col_w - 7}}'
            f' {col.min():>+8.2f}'
            f' {col.max():>+8.2f}'
            f' {col.mean():>+8.2f}'
            f' {r2:>8.4f}'
            f' {len(col):>6}'
        )

    # Graph
    os.makedirs(GRAPHS_DIR, exist_ok=True)
    slug = f'{start_label}_{end_label}' if start_label != end_label else start_label
    clip = ''
    if args.min is not None:
        clip += f'_min{args.min:g}'
    if args.max is not None:
        clip += f'_max{args.max:g}'
    output_path = os.path.join(GRAPHS_DIR, f'ozone_{slug}_{args.resample}{clip}.png')

    local_df = df.tz_convert(settings.DEFAULT_TIMEZONE)

    fig, ax = plt.subplots(figsize=(14, 5))
    colors = plt.cm.tab10.colors

    for i, device_id in enumerate(present):
        col = local_df[device_id].dropna()
        ax.plot(col.index, col.values,
                label=f'AQLite-{device_id}',
                color=colors[i % len(colors)],
                linewidth=0.8, alpha=0.9)

    fleet_mean = local_df['_fleet_mean']
    ax.plot(fleet_mean.index, fleet_mean.values,
            label='Fleet mean',
            color='black', linewidth=1.2, linestyle='--', alpha=0.6, zorder=5)

    tz_abbr = datetime.now(settings.DEFAULT_TIMEZONE).strftime('%Z')
    date_range = f'{start_label} → {end_label}' if start_label != end_label else start_label
    ax.set_title(f'AQLite Ozone  {date_range}  ({args.resample} avg)', fontsize=13)
    ax.set_xlabel(f'Time ({tz_abbr})')
    ax.set_ylabel('O₃ (ppb)')
    ax.legend(loc='best', fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d %H:%M', tz=settings.DEFAULT_TIMEZONE))
    fig.autofmt_xdate()
    plt.tight_layout()

    plt.savefig(output_path, dpi=150)
    print(f'\nGraph saved: {output_path}')


if __name__ == '__main__':
    main()
