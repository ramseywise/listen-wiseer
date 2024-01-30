import os
import pandas as pd
from sklearn.pipeline import Pipeline
from sklearn.ensemble import RandomForestClassifier
from sklearn.neighbors import KNeighborsClassifier
from sklearn.tree import DecisionTreeClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.feature_selection import RFE

# from sklearn.model_selection import KFold
from sklearn.model_selection import cross_val_score, train_test_split

from sklearn.metrics import (
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
    accuracy_score,
)
from const import *
import logger

os.chdir("/Users/wiseer/Documents/github/listen-wiseer/src/")
log = logger.get_logger("app")


# TODO: Turn into class and separate functions with models defined


def fit_and_evaluate(y_true, y_pred):
    """Return metrics to evaluate model performance."""
    log.info("Evaluating models")
    f1 = round(f1_score(y_true, y_pred), 2)
    roc_auc = round(roc_auc_score(y_true, y_pred), 2)
    accuracy = round(accuracy_score(y_true, y_pred), 2)
    precision = round(precision_score(y_true, y_pred), 2)
    recall = round(recall_score(y_true, y_pred), 2)
    # specificity = round(specificity_score(y_true, y_pred), 2)

    return accuracy, precision, recall, f1, roc_auc  # specificicty


def return_model_metrics(metrics):
    results = pd.DataFrame(metrics)
    results["model"] = [
        "Logistic Regression",
        "Decision Tree",
        "Random Forest",
    ]
    results = results[["model", "accuracy", "precision", "recall", "f1", "roc_auc"]]
    return results


def return_feature_selection(rfe_features):
    log.info("Selecting features")
    feature_selection = pd.DataFrame(rfe_features).T
    feature_selection.columns = [
        "Logistic",
        "Decision Tree",
        "Random Forest",
    ]

    return feature_selection


def config_model_pipeline():
    """Builds pipeline for sklearn models and returns model metrics."""
    pipelines = []
    pipelines.append(
        Pipeline(
            [
                (
                    "scaler",
                    MinMaxScaler(),
                ),
                (
                    "rfe",
                    RFE(
                        estimator=LogisticRegression(),
                        n_features_to_select=15,
                    ),
                ),
                ("classifier", LogisticRegression()),
            ]
        )
    )
    pipelines.append(
        Pipeline(
            [
                (
                    "scaler",
                    MinMaxScaler(),
                ),
                (
                    "rfe",
                    RFE(
                        estimator=DecisionTreeClassifier(),
                        n_features_to_select=15,
                    ),
                ),
                ("classifier", DecisionTreeClassifier()),
            ]
        )
    )
    pipelines.append(
        Pipeline(
            [
                (
                    "scaler",
                    MinMaxScaler(),
                ),
                (
                    "rfe",
                    RFE(
                        estimator=RandomForestClassifier(n_estimators=100),
                        n_features_to_select=15,
                    ),
                ),
                ("classifier", RandomForestClassifier(n_estimators=100)),
            ]
        )
    )
    return pipelines


def fit_models(df):
    # TODO: incorporate train data into data flow pipeline when DB is setup
    X = transform_feature_data(df)  # TODO: problem with transofming in pipeline
    y = pd.read_csv(
        "/Users/wiseer/Documents/github/listen-wiseer/src/data/faves.csv",
        index_col=0,
    )
    y = np.array(y["faves"]).ravel()

    # TODO: add smote/k-fold validation

    ## Drop features with correlation greater than 0.95
    # corr_matrix = X.corr().abs()
    # upper = corr_matrix.where(np.triu(np.ones(corr_matrix.shape), k=1).astype(bool))
    # to_drop = [column for column in upper.columns if any(upper[column] > 0.95)]
    # df.drop(to_drop, axis=1, inplace=True)

    # Splitting Dataset
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.3, random_state=0
    )

    log.info("Fitting models")
    pipelines = config_model_pipeline()
    metrics = []
    rfe_features = []
    rfe_values = []
    for model in pipelines:
        model.fit(X_train, y_train)
        rfe_features = model.named_steps["rfe"].support_
        rfe_features = list(X.columns[rfe_features])
        rfe_features.append(rfe_features)
        rfe_values = list(model.named_steps["rfe"].estimator_.feature_importances_)
        rfe_values.append(rfe_values)
        y_true = y_test
        y_pred = model.predict(X_test)
        accuracy, precision, recall, f1, roc_auc = fit_and_evaluate(y_true, y_pred)
        metrics.append(
            {
                "accuracy": accuracy,
                "precision": precision,
                "recall": recall,
                "f1": f1,
                "roc_auc": roc_auc,
            }
        )
    metrics = return_model_metrics(metrics)
    feature_selection = return_feature_selection(rfe_features)

    # TODO: add model selection and hyperparameter tuning; when model is selected retraino on selected features

    return metrics, feature_selection
