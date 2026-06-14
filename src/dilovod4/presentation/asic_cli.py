"""CLI для ASiC-контейнерів (ETSI EN 319 162-1) — пакування й перегляд.

Підкоманди:
  pack     зібрати ASiC-E з файлу даних і готових detached-підписів над
           манІфестами (підписи робляться окремо — токеном/UAPKI)
  manifest вивести точні байти ASiCManifestNNN.xml, які підписувач має підписати
           (detached CAdES) — корисно для зовнішнього підпису
  sign     підписати файл апаратним токеном одразу в ASiC-E (нативний CtxASiCSign)
  inspect  розібрати наявний ASiC: тип, файли даних, підписи, манІфести

Приклади:
  # 1) дізнатися, що підписувати (манІфест для 1-го підпису)
  dilovod4-asic manifest doc.pdf -n 1 > manifest001.xml
  # 2) підписати manifest001.xml detached токеном/UAPKI -> sig1.p7s
  # 3) зібрати контейнер
  dilovod4-asic pack doc.pdf -s sig1.p7s -s sig2.p7s -o doc.asice
  # переглянути
  dilovod4-asic inspect doc.asice

  # або підпис токеном напряму в ASiC-E (PIN через TOKEN_PIN):
  TOKEN_PIN=*** dilovod4-asic sign doc.pdf --cmp ca.tax.gov.ua/services/cmp/ \\
      --tsp ca.tax.gov.ua/services/tsp/ --ocsp ca.tax.gov.ua/services/ocsp/ -t
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Sequence

from ..infrastructure.asic import (
    AsicSignature,
    build_asic_e,
    manifest_for,
    read_asic,
)


def _read(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def _cmd_manifest(args: argparse.Namespace) -> int:
    data_files = [(os.path.basename(args.datafile), _read(args.datafile))]
    xml = manifest_for(args.number, data_files)
    if args.output:
        with open(args.output, "wb") as fh:
            fh.write(xml)
        print(f"ASiCManifest{args.number:03d}.xml -> {args.output} ({len(xml)} байт)",
              file=sys.stderr)
    else:
        sys.stdout.buffer.write(xml)
    return 0


def _cmd_pack(args: argparse.Namespace) -> int:
    data_files = [(os.path.basename(args.datafile), _read(args.datafile))]
    sigs = [AsicSignature(_read(p), label=os.path.basename(p)) for p in args.signature]
    if not sigs:
        print("потрібна щонайменше одна підпис (-s)", file=sys.stderr)
        return 2
    out = args.output or args.datafile + ".asice"
    build_asic_e(data_files, sigs, out)
    print(f"OK: {out} ({os.path.getsize(out)} байт, {len(sigs)} підпис(ів))")
    print("  кожна підпис має покривати відповідний ASiCManifestNNN.xml "
          "(див. підкоманду manifest)", file=sys.stderr)
    return 0


def _cmd_sign(args: argparse.Namespace) -> int:
    pin = os.environ.get("TOKEN_PIN")
    if not pin:
        print("встановіть TOKEN_PIN (не передавайте PIN в аргументах)", file=sys.stderr)
        return 2
    # ліниві імпорти — токен потрібен лише тут
    from ..infrastructure.token_sign import (
        TokenError,
        TokenHostNotFound,
        asic_sign_with_token,
    )
    out = args.output or args.datafile + ".asice"
    try:
        res = asic_sign_with_token(
            file_path=args.datafile,
            pin=pin,
            cmp_url=args.cmp,
            out_path=out,
            with_timestamp=args.timestamp,
            tsp_url=args.tsp,
            ocsp_url=args.ocsp,
            type_index=args.type_index,
            dev_index=args.dev_index,
        )
    except TokenHostNotFound as exc:
        print(f"ПОМИЛКА: {exc}", file=sys.stderr)
        return 2
    except TokenError as exc:
        print(f"ПОМИЛКА: {exc}", file=sys.stderr)
        return 3
    fmt = "CAdES-T" if args.timestamp else "CAdES-BES"
    print(f"OK: {out} ({len(res.container)} байт, {fmt}, "
          f"позначка часу={res.has_timestamp})")
    return 0


def _cmd_inspect(args: argparse.Namespace) -> int:
    info = read_asic(args.container)
    print(f"Тип контейнера : {info['type']}")
    print(f"Файли даних    : {', '.join(info['data_files']) or '—'}")
    print(f"Підписи        : {len(info['signatures'])}")
    for s in info["signatures"]:
        print(f"  - {s}")
    print(f"Маніфести      : {len(info['manifests'])}")
    for m in info["manifests"]:
        print(f"  - {m}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dilovod4-asic",
        description="Пакування та перегляд ASiC-контейнерів (ETSI EN 319 162-1).",
    )
    sub = p.add_subparsers(dest="command", required=True)

    pm = sub.add_parser("manifest", help="вивести ASiCManifestNNN.xml для підпису")
    pm.add_argument("datafile", help="файл даних")
    pm.add_argument("-n", "--number", type=int, default=1,
                    help="номер підпису (1-based), типово 1")
    pm.add_argument("-o", "--output", help="куди записати XML (типово stdout)")
    pm.set_defaults(func=_cmd_manifest)

    pp = sub.add_parser("pack", help="зібрати ASiC-E з готових detached-підписів")
    pp.add_argument("datafile", help="файл даних")
    pp.add_argument("-s", "--signature", action="append", default=[],
                    help="detached .p7s над відповідним манІфестом (повторюваний)")
    pp.add_argument("-o", "--output", help="вихідний .asice (типово <datafile>.asice)")
    pp.set_defaults(func=_cmd_pack)

    ps = sub.add_parser("sign", help="підписати токеном одразу в ASiC-E")
    ps.add_argument("datafile", help="файл даних")
    ps.add_argument("--cmp", default="ca.tax.gov.ua/services/cmp/",
                    help="CMP-адреса КНЕДП-емітента (повний шлях)")
    ps.add_argument("--tsp", default="ca.tax.gov.ua/services/tsp/", help="TSP-адреса")
    ps.add_argument("--ocsp", default="ca.tax.gov.ua/services/ocsp/", help="OCSP-адреса")
    ps.add_argument("-t", "--timestamp", action="store_true",
                    help="CAdES-T (квал. позначка часу, Art.26.4)")
    ps.add_argument("--type-index", type=int, default=1, help="індекс типу носія")
    ps.add_argument("--dev-index", type=int, default=0, help="індекс пристрою носія")
    ps.add_argument("-o", "--output", help="вихідний .asice")
    ps.set_defaults(func=_cmd_sign)

    pi = sub.add_parser("inspect", help="розібрати наявний ASiC")
    pi.add_argument("container", help="шлях до .asice/.asics")
    pi.set_defaults(func=_cmd_inspect)

    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (OSError, ValueError) as exc:
        print(f"ПОМИЛКА: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
