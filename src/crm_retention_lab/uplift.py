"""Two frozen three-arm T-learners fitted exclusively on settled train rows.

Only the eleven pre-assignment feature columns enter preprocessing. The output
contains conditional outcome means, not identified individual treatment effects.
The bundle is a private model artifact; its manifest contains aggregate metadata.
"""

import copy
from datetime import timedelta
import math
from numbers import Real

from .config import parse_ts
from .marts import FEATURE_COLUMNS


ARM_ORDER = ("control", "info", "coupon")
MODEL_NAMES = ("ridge", "hgb")
CATEGORICAL_COLUMNS = ("acquisition_channel", "first_delivery_month")
NUMERIC_COLUMNS = tuple(column for column in FEATURE_COLUMNS if column not in CATEGORICAL_COLUMNS)
OUTCOMES = {"profit": "contribution_profit_60d_krw", "unsubscribe": "unsubscribe_60d", "refund": "refund_customer_flag"}
DEFAULT_MODEL_SPEC = {
    "random_state": 20261108,
    "ridge": {"alpha": 100.0},
    "logistic": {"C": 1.0, "max_iter": 1000, "class_weight": None},
    "hgb": {"max_leaf_nodes": 15, "min_samples_leaf": 80, "l2_regularization": 10.0,
            "max_iter": 120, "learning_rate": 0.05, "early_stopping": False},
}


def _model_spec(spec):
    result = copy.deepcopy(DEFAULT_MODEL_SPEC)
    if spec is None:
        return result
    if not isinstance(spec, dict) or set(spec) - set(result):
        raise ValueError("Only the prespecified model keys are permitted")
    for key, value in spec.items():
        if key == "random_state":
            if type(value) is not int or not 0 <= value < 2 ** 32:
                raise ValueError("random_state must be an integer in [0, 2**32)")
            result[key] = value
        else:
            if not isinstance(value, dict) or set(value) - set(result[key]):
                raise ValueError(f"Unknown {key} model parameter")
            for parameter, setting in value.items():
                if setting != result[key][parameter] or (isinstance(setting, bool) != isinstance(result[key][parameter], bool)):
                    raise ValueError(f"{key}.{parameter} differs from the frozen candidate specification")
                result[key][parameter] = setting
    return result


def _validate_train(marts):
    metadata = marts["metadata"]
    if metadata.get("analysis_scope") != "train":
        raise ValueError("Uplift models may be fitted only on train marts")
    if list(metadata["feature_columns"]) != list(FEATURE_COLUMNS):
        raise ValueError("Feature metadata must contain only the fixed pre-assignment allowlist")
    as_of = parse_ts(metadata["as_of"])
    if as_of > min(parse_ts(metadata["cutoff"]), parse_ts(metadata["train_labels_available_by"])):
        raise ValueError("Training labels exceed the permitted knowledge cutoff")
    train_start = parse_ts(metadata["train_start_inclusive"])
    train_end = parse_ts(metadata["train_end_exclusive"])
    if as_of < train_end:
        raise ValueError("The training assignment roster is not complete")
    features = marts["features"]
    outcome_rows = marts["outcomes"]
    feature_ids = [row["assignment_id"] for row in features]
    outcomes = {row["assignment_id"]: row for row in outcome_rows}
    if len(set(feature_ids)) != len(features) or len(outcomes) != len(outcome_rows):
        raise ValueError("Duplicate assignments are not allowed")
    if set(feature_ids) != set(outcomes):
        raise ValueError("Training feature and outcome assignments must match")
    if len({row["customer_id"] for row in features}) != len(features):
        raise ValueError("A customer may contribute only one training assignment")
    if (metadata["selected_assignments"] != len(features)
            or marts["eligibility_flow"]["assigned_total"] != len(features)):
        raise ValueError("Training ITT denominators do not match")
    counts = {arm: 0 for arm in ARM_ORDER}
    aligned = []
    for feature in features:
        outcome = outcomes[feature["assignment_id"]]
        arm = feature["arm"]
        if arm not in counts:
            raise ValueError("Unknown training arm")
        for field in ("customer_id", "arm", "assigned_at"):
            if feature[field] != outcome[field]:
                raise ValueError(f"Training feature/outcome {field} mismatch")
        assigned = parse_ts(feature["assigned_at"])
        if not train_start <= assigned < train_end or assigned >= as_of:
            raise ValueError("A validation, test or otherwise out-of-train assignment entered fitting")
        if parse_ts(feature["feature_cutoff_at"]) != assigned:
            raise ValueError("Features must be frozen at the pre-assignment cutoff")
        freeze = assigned + timedelta(days=90)
        if (outcome["is_outcome_mature"] is not True or outcome["is_profit_settled"] is not True
                or outcome["label_freeze_at"] is None or parse_ts(outcome["label_freeze_at"]) != freeze
                or freeze > as_of):
            raise ValueError("Every training assignment must have a settled 90-day label")
        if outcome.get("settlement_end_at") is not None and parse_ts(outcome["settlement_end_at"]) != freeze:
            raise ValueError("Inconsistent settlement endpoint")
        for metric in (*OUTCOMES.values(), "repeat_paid_within_60d"):
            value = outcome[metric]
            if metric == OUTCOMES["profit"]:
                if type(value) is not int:
                    raise ValueError("Profit labels must be integer KRW, including zero and negative outcomes")
            elif type(value) not in (int, bool) or value not in (0, 1):
                raise ValueError("Settled risk and repeat labels must be binary")
        aligned.append(outcome)
        counts[arm] += 1
    if any(count < 2 for count in counts.values()):
        raise ValueError("Each training arm requires at least two customers")
    original = marts["eligibility_flow"].get("assigned_by_arm")
    if original is not None and original != counts:
        raise ValueError("Training arm denominators disagree with original assignments")
    return features, aligned, counts


def _feature_matrix(features):
    import numpy as np

    matrix = np.empty((len(features), len(FEATURE_COLUMNS)), dtype=object)
    for row_index, row in enumerate(features):
        missing = set(FEATURE_COLUMNS) - set(row)
        if missing:
            raise ValueError(f"Missing required feature columns: {sorted(missing)}")
        for column_index, column in enumerate(FEATURE_COLUMNS):
            value = row[column]
            if column == "acquisition_channel":
                if value is not None and not isinstance(value, str):
                    raise ValueError("acquisition_channel must be text or null")
                matrix[row_index, column_index] = "__missing__" if value is None else value
            elif column == "first_delivery_month":
                if value is not None and (isinstance(value, bool) or not isinstance(value, Real)
                                          or not math.isfinite(value) or int(value) != value or not 1 <= value <= 12):
                    raise ValueError("first_delivery_month must be an integer month or null")
                matrix[row_index, column_index] = "__missing__" if value is None else str(int(value))
            else:
                if value is None or (isinstance(value, Real) and not isinstance(value, bool) and math.isnan(value)):
                    matrix[row_index, column_index] = np.nan
                elif isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
                    raise ValueError(f"{column} must be finite numeric data or null")
                else:
                    matrix[row_index, column_index] = float(value)
    return matrix


def _preprocessor(scale):
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import MissingIndicator, SimpleImputer
    from sklearn.pipeline import FeatureUnion, Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    numeric = FeatureUnion([
        ("values", SimpleImputer(strategy="median", keep_empty_features=True)),
        ("missing", MissingIndicator(features="all")),
    ])
    if scale:
        numeric = Pipeline([("impute_and_flag", numeric), ("scale", StandardScaler())])
    return ColumnTransformer([
        ("numeric", numeric, [FEATURE_COLUMNS.index(column) for column in NUMERIC_COLUMNS]),
        ("categorical", OneHotEncoder(handle_unknown="ignore", sparse_output=False),
         [FEATURE_COLUMNS.index(column) for column in CATEGORICAL_COLUMNS]),
    ], remainder="drop", sparse_threshold=0)


def _binary_model(x, y, family, spec):
    import numpy as np
    from sklearn.dummy import DummyClassifier
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression

    classes = np.unique(y)
    if len(classes) == 1:
        estimator = DummyClassifier(strategy="constant", constant=int(classes[0]))
        status = "constant_probability_single_class"
    elif family == "ridge":
        estimator = LogisticRegression(**spec["logistic"], solver="lbfgs", random_state=spec["random_state"])
        status = "fitted_logistic"
    else:
        estimator = HistGradientBoostingClassifier(**spec["hgb"], categorical_features=None,
                                                  class_weight=None, random_state=spec["random_state"])
        status = "fitted_hgb_classifier"
    estimator.fit(x, y)
    return estimator, status


def fit_uplift_models(train_marts, model_spec=None):
    """Fit both frozen candidates using all original settled training assignments.

    Preprocessors fit once on the pooled train covariates, then each arm model
    sees only that arm's outcomes. No validation fitting, calibration, internal
    early-stopping split, trimming or transformation of profit outcomes occurs.
    """
    spec = _model_spec(model_spec)
    features, outcomes, counts = _validate_train(train_marts)
    import numpy as np
    import sklearn
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.linear_model import Ridge
    from threadpoolctl import threadpool_limits

    matrix = _feature_matrix(features)
    arm_indices = {arm: np.asarray([index for index, row in enumerate(features) if row["arm"] == arm]) for arm in ARM_ORDER}
    preprocessors, models, fit_status = {}, {}, {}
    # Fixed single-thread fitting avoids host-dependent OpenMP oversubscription;
    # it changes computation resources, not the prespecified candidate set.
    with threadpool_limits(limits=1):
        for family in MODEL_NAMES:
            processor = _preprocessor(scale=family == "ridge")
            transformed = processor.fit_transform(matrix)
            preprocessors[family] = processor
            models[family] = {metric: [] for metric in OUTCOMES}
            fit_status[family] = {}
            for arm in ARM_ORDER:
                indices = arm_indices[arm]
                x = transformed[indices]
                fit_status[family][arm] = {}
                for name, metric in OUTCOMES.items():
                    y = np.asarray([outcomes[index][metric] for index in indices], dtype=float if name == "profit" else int)
                    if name == "profit":
                        estimator = (Ridge(**spec["ridge"], solver="svd") if family == "ridge" else
                                     HistGradientBoostingRegressor(**spec["hgb"], loss="squared_error",
                                                                  categorical_features=None, random_state=spec["random_state"]))
                        estimator.fit(x, y)
                        status = "fitted_untransformed_profit"
                    else:
                        estimator, status = _binary_model(x, y, family, spec)
                    models[family][name].append(estimator)
                    fit_status[family][arm][name] = status
        control = arm_indices["control"]
        control_repeat, repeat_status = _binary_model(
            preprocessors["ridge"].transform(matrix)[control],
            np.asarray([outcomes[index]["repeat_paid_within_60d"] for index in control], dtype=int),
            "ridge", spec,
        )
    metadata = train_marts["metadata"]
    manifest = {
        "model_bundle_version": "0.1.0", "analysis_scope": "train", "fit_as_of": metadata["as_of"],
        "input_simulation_id": metadata["input_simulation_id"], "n_train": len(features), "n_by_arm": counts,
        "arm_order": list(ARM_ORDER), "model_names": list(MODEL_NAMES),
        "feature_columns": list(FEATURE_COLUMNS), "numeric_columns": list(NUMERIC_COLUMNS),
        "categorical_columns": list(CATEGORICAL_COLUMNS), "model_spec": spec,
        "fit_status": fit_status, "control_repeat_status": repeat_status,
        "preprocessing_fit_scope": "pooled train covariates only; never validation or final-test rows",
        "numeric_preprocessing": "train medians; all numeric missing indicators; StandardScaler for ridge/logistic only",
        "categorical_preprocessing": "dense one-hot on train categories; unknown categories ignored",
        "profit_transformation": "none; zero and negative KRW retained; predictions not clipped",
        "risk_output": "positive-class probabilities from LogisticRegression or HGBClassifier",
        "control_repeat_risk_semantics": "P(repeat_paid_within_60d=1 | control, X); nonrepeat risk is 1 minus this value",
        "control_repeat_model": "fixed train-control LogisticRegression with ridge-family preprocessing",
        "dr_evaluator_selection": "not selected here; pipeline must prespecify a common evaluator before validation comparison",
        "transformed_feature_counts": {name: len(processor.get_feature_names_out()) for name, processor in preprocessors.items()},
        "training_feature_names": {name: processor.get_feature_names_out(list(FEATURE_COLUMNS)).tolist() for name, processor in preprocessors.items()},
        "software": {"numpy": np.__version__, "scikit_learn": sklearn.__version__},
        "fit_thread_limit": 1, "oracle_used": False, "validation_fit": False, "final_test_used": False,
    }
    return {"models": models, "preprocessors": preprocessors, "control_repeat_model": control_repeat, "manifest": manifest}


def _positive_probability(estimator, matrix):
    import numpy as np

    classes = list(estimator.classes_)
    if 1 not in classes:
        return np.zeros(len(matrix), dtype=float)
    return np.asarray(estimator.predict_proba(matrix)[:, classes.index(1)], dtype=float)


def predict_uplift_models(bundle, features):
    """Predict in input row order; columns are control, info and coupon.

    Values under ``control_repeat_risk`` are repeat probabilities, not nonrepeat
    probabilities. This private output contains no copied customer identifiers.
    Predicting never fits, calibrates or updates preprocessing statistics.
    """
    import numpy as np
    from threadpoolctl import threadpool_limits

    manifest = bundle["manifest"]
    if (manifest["feature_columns"] != list(FEATURE_COLUMNS)
            or manifest["arm_order"] != list(ARM_ORDER) or manifest["model_names"] != list(MODEL_NAMES)):
        raise ValueError("Model bundle does not match the fixed feature/arm contract")
    matrix = _feature_matrix(features)
    if not features:
        return {**{name: {metric: np.empty((0, 3), dtype=float) for metric in OUTCOMES} for name in MODEL_NAMES},
                "control_repeat_risk": np.empty(0, dtype=float)}
    result = {}
    with threadpool_limits(limits=1):
        for family in MODEL_NAMES:
            transformed = bundle["preprocessors"][family].transform(matrix)
            result[family] = {}
            for metric in OUTCOMES:
                estimators = bundle["models"][family][metric]
                if len(estimators) != 3:
                    raise ValueError("Each outcome must contain exactly three arm estimators")
                predictions = [np.asarray(estimator.predict(transformed), dtype=float) if metric == "profit"
                               else _positive_probability(estimator, transformed) for estimator in estimators]
                values = np.column_stack(predictions)
                if not np.isfinite(values).all():
                    raise ValueError("Model produced nonfinite predictions")
                if metric != "profit" and ((values < 0).any() or (values > 1).any()):
                    raise ValueError("Risk model produced values outside [0, 1]")
                result[family][metric] = values
        repeat = _positive_probability(bundle["control_repeat_model"], bundle["preprocessors"]["ridge"].transform(matrix))
        if not np.isfinite(repeat).all() or ((repeat < 0).any() or (repeat > 1).any()):
            raise ValueError("Control repeat model produced invalid probabilities")
        result["control_repeat_risk"] = repeat
    return result
