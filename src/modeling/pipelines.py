import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.neighbors import KNeighborsClassifier
from sklearn.tree import DecisionTreeClassifier
from sklearn.linear_model import LogisticRegression
#from sklearn.model_selection import KFold
from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.pipeline import Pipeline
from modeling.const import *
from modeling.preprocessing import *
from sklearn.ensemble import IsolationForest
from sklearn.metrics import (
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
    accuracy_score,
)


def fit_and_evaluate(y_true, y_pred):
    """Return metrics to evaluate model performance."""
    f1 = round(f1_score(y_true, y_pred), 2)
    roc_auc = round(roc_auc_score(y_true, y_pred), 2)
    accuracy = round(accuracy_score(y_true, y_pred), 2)
    precision = round(precision_score(y_true, y_pred), 2)
    recall = round(recall_score(y_true, y_pred), 2)
    # specificity = round(specificity_score(y_true, y_pred), 2)

    return accuracy, precision, recall, f1, roc_auc  # specificicty


def return_model_metrics(df):
    # NOTE: these models only use fit, not fit_transform
    pipelines = []
    pipelines.append(Pipeline(steps=[("lr", LogisticRegression())]))
    pipelines.append(Pipeline(steps=[("rf", RandomForestClassifier())]))
    pipelines.append(Pipeline(steps=[("dt", DecisionTreeClassifier())]))
    pipelines.append(Pipeline(steps=[("if", IsolationForest())]))
    pipelines.append(Pipeline(steps=[("kn", KNeighborsClassifier())]))

    # TODO: incorporate train data into data flow pipeline when DB is setup
    X = transform_feature_data(df)
    y = pd.read_csv(
        "/Users/wiseer/Documents/github/listen-wiseer/src/data/faves.csv",
        index_col=0,
    )
    y.set_index("id", inplace=True)

    # TODO: add smote/k-fold validation
    # Splitting Dataset
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.3, random_state=0
    )

    scores = []
    for model in pipelines:
        model.fit(X_train, y_train)
        y_true = y_test
        y_pred = model.predict(X_test)
        # y_pred = np.where(y_pred == 1, 0, 1)
        accuracy, precision, recall, f1, roc_auc = fit_and_evaluate(y_true, y_pred)
        scores.append(
            {
                "accuracy": accuracy,
                "precision": precision,
                "recall": recall,
                "f1": f1,
                "roc_auc": roc_auc,
            }
        )
    results = pd.DataFrame(scores)
    results["model"] = [
        "Logistic Regression",
        "Random Forest",
        "Decision Tree",
        "Isolation Forest",
    ]
    results = results[["model", "accuracy", "precision", "recall", "f1", "roc_auc"]]
    return results
