"""Source-checkout commands for generation, diagnostics and validation."""

import argparse
import json
import sys
import unittest
from pathlib import Path

from .config import SUPPORTED_SCENARIOS, load_config, validate_config
from .storage import check_output_separation, load_observed, verify_run_hashes, write_run


def main(argv=None):
    parser = argparse.ArgumentParser(description="Synthetic CRM lab: generate, validate, diagnose, compare-arms, sample, test")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("generate", "sample"):
        command = commands.add_parser(name)
        command.add_argument("--config", type=Path, default=Path("configs/smoke_v0_1.json"))
        command.add_argument("--output", type=Path, required=True)
        command.add_argument("--customers", type=int, default=20 if name == "sample" else None)
        command.add_argument("--seed", type=int)
        command.add_argument("--scenario", choices=SUPPORTED_SCENARIOS)
        if name == "generate":
            command.add_argument("--oracle-output", type=Path, required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--run-dir", type=Path, required=True)
    for name in ("diagnose", "compare-arms"):
        analysis = commands.add_parser(name)
        analysis.add_argument("--run-dir", type=Path, required=True)
        analysis.add_argument("--output", type=Path, required=True)
        analysis.add_argument("--report-dir", type=Path, default=Path("report"))
        analysis.add_argument("--as-of", help="Optional exclusive knowledge cutoff; capped at the train readout")
        analysis.add_argument("--static-svg", action="store_true")
    test = commands.add_parser("test")
    test.add_argument("--pattern", default="test_*.py")
    select = commands.add_parser("select-policy", help="Fit on train, screen validation and freeze a policy")
    select.add_argument("--train-run", type=Path, required=True)
    select.add_argument("--validation-run", type=Path, required=True)
    select.add_argument("--output", type=Path, required=True)
    select.add_argument("--final-run", type=Path, required=True)
    select.add_argument("--config", type=Path, default=Path("configs/policy_analysis_v0_1.json"))
    evaluate = commands.add_parser("evaluate-policy", help="Evaluate the frozen policy once on independent final data")
    evaluate.add_argument("--policy-dir", type=Path, required=True)
    evaluate.add_argument("--generate-final", action="store_true")
    report_policy = commands.add_parser("report-policy", help="Append saved policy aggregates to the existing report")
    report_policy.add_argument("--policy-dir", type=Path, required=True)
    report_policy.add_argument("--report-dir", type=Path, default=Path("report"))
    report_policy.add_argument("--static-svg", action="store_true")
    args = parser.parse_args(argv)

    try:
        if args.command == "test":
            root = Path(__file__).resolve().parents[2]
            suite = unittest.defaultTestLoader.discover(str(root / "tests"), pattern=args.pattern)
            result = unittest.TextTestRunner(verbosity=2).run(suite)
            return 0 if result.wasSuccessful() else 1

        from .contracts import validate_dataset

        if args.command == "select-policy":
            from .policy_pipeline import fit_select_lock
            result = fit_select_lock(args.train_run, args.validation_run, args.output, args.config, args.final_run)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "evaluate-policy":
            from .policy_pipeline import evaluate_locked_policy
            print(json.dumps(evaluate_locked_policy(args.policy_dir, generate_final=args.generate_final), ensure_ascii=False, indent=2))
            return 0
        if args.command == "report-policy":
            from .policy_report import append_policy_report
            print(json.dumps(append_policy_report(args.policy_dir, args.report_dir, static_svg=args.static_svg), ensure_ascii=False, indent=2))
            return 0

        if args.command in ("diagnose", "compare-arms"):
            from .reporting import run_diagnosis
            result = run_diagnosis(args.run_dir, args.output, args.report_dir,
                                   as_of=args.as_of, static_svg=args.static_svg,
                                   include_experiment=args.command == "compare-arms")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        if args.command == "validate":
            config = verify_run_hashes(args.run_dir)
            validate_config(config)
            observed = load_observed(args.run_dir / "observed")
            report = validate_dataset(observed, config)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report["valid"] else 1

        oracle_output = getattr(args, "oracle_output", None)
        check_output_separation(args.output, oracle_output)
        config = load_config(args.config, customers=args.customers, seed=args.seed, scenario=args.scenario)
        if args.command == "sample":
            config["runtime"]["purpose"] = "public_synthetic_schema_sample_not_effect_evidence"
        from .simulation import generate_dataset

        observed, oracle = generate_dataset(config)
        report = validate_dataset(observed, config)
        if not report["valid"]:
            print(json.dumps(report, ensure_ascii=False, indent=2), file=sys.stderr)
            return 1
        manifest = write_run(args.output, observed, oracle, config, report, oracle_output=oracle_output)
        print(json.dumps({"output": str(args.output), "valid": True,
                          "simulation_id": manifest["simulation_id"],
                          "summary": manifest["summary"]}, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError, ImportError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
