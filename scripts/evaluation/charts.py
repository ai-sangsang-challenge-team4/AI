"""Standalone aggregate figures. No complaint text or evidence enters a chart."""
from __future__ import annotations


def check_available():
    try:
        import matplotlib
    except ImportError as exc:
        raise ValueError("--charts requires: python -m pip install -r requirements-evaluation.txt") from exc
    matplotlib.use("Agg")


def render_charts(directory, metrics, manifest):
    check_available()
    import matplotlib.pyplot as plt

    context = f"{manifest['execution']} | successful {metrics['coverage']['succeeded_cases']}/{metrics['coverage']['requested_cases']} cases"
    capture = manifest.get('backend_capture')
    if capture:
        context = f"Backend {capture['prediction_view']} | {capture['capture_status']} | " + context
    names = list(metrics["per_tag"])
    policies = list(metrics["binary"])
    fig, ax = plt.subplots(figsize=(11, 5), layout="constrained")
    width = 0.8 / len(policies)
    for index, policy in enumerate(policies):
        values = [metrics["per_tag"][code]["binary"][policy]["f1"] for code in names]
        positions = [i - 0.4 + width / 2 + index * width for i in range(len(names))]
        bars = ax.bar(positions, [v if v is not None else 0 for v in values], width, label=policy)
        for bar, value in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width()/2, (value or 0) + .02,
                    "n/a" if value is None else f"{value:.2f}", ha="center", fontsize=8)
    ax.set(xticks=range(len(names)), xticklabels=names, ylim=(0, 1.12), ylabel="F1",
           title="Tag F1 (REPEAT excluded)\n" + context)
    ax.tick_params(axis="x", labelrotation=20)
    ax.legend()
    fig.savefig(directory / "tag_f1.png", dpi=160)
    plt.close(fig)

    def matrix_plot(matrix, filename, title):
        labels = list(matrix)
        values = [[matrix[g][p] for p in labels] for g in labels]
        fig, ax = plt.subplots(figsize=(7, 6), layout="constrained")
        heat = ax.imshow(values, cmap="Blues", vmin=0)
        for i, row in enumerate(values):
            for j, value in enumerate(row):
                ax.text(j, i, str(value), ha="center", va="center",
                        color="white" if value > max(map(max, values), default=0) / 2 else "black")
        ax.set(xticks=range(len(labels)), xticklabels=labels, yticks=range(len(labels)), yticklabels=labels,
               xlabel="Predicted", ylabel="Gold", title=title + "\n" + context)
        fig.colorbar(heat, ax=ax, label="Count")
        fig.savefig(directory / filename, dpi=160)
        plt.close(fig)

    matrix_plot(metrics["confusion_matrix"], "tag_state_confusion.png", "Tag states (successful labels only)")
    if metrics["final_risk"]["successful_cases"]:
        matrix_plot(metrics["final_risk"]["confusion_matrix"], "risk_confusion.png",
                    f"Final risk (paired cases n={metrics['final_risk']['successful_cases']})")
    cohorts = [(f"{code}\n{subtype}", group)
               for code, groups in metrics["context_subtypes"]["per_tag"].items()
               for subtype, group in groups.items() if group["annotated_labels"]]
    if cohorts:
        fig, ax = plt.subplots(figsize=(12, 5), layout="constrained")
        for index, policy in enumerate(policies):
            values = [group["binary"][policy]["f1"] for _, group in cohorts]
            positions = [i - .4 + width/2 + index*width for i in range(len(cohorts))]
            ax.bar(positions, [v if v is not None else 0 for v in values], width, label=policy)
            for position, value in zip(positions, values):
                ax.text(position, (value or 0) + .02, "n/a" if value is None else f"{value:.2f}", ha="center", fontsize=8)
        ax.set(xticks=range(len(cohorts)), xticklabels=[name for name, _ in cohorts], ylim=(0, 1.12), ylabel="F1",
               title="Human-confirmed context cohorts (may overlap)\n" + context)
        ax.tick_params(axis="x", labelrotation=15)
        ax.legend()
        fig.savefig(directory / "context_subtype_f1.png", dpi=160)
        plt.close(fig)
