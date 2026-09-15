from disaster_monitor.infrastructure.hazard_context.inform import InformRiskDataset


def test_inform_context_is_baseline_not_event_impact(tmp_path) -> None:
    dataset = tmp_path / "inform.csv"
    dataset.write_text(
        "iso3,place_name,aggregation_level,vintage,risk,vulnerability,coping_capacity\n"
        "VNM,Viet Nam,national,2026,4.2,3.8,5.1\n"
    )

    result = InformRiskDataset(dataset, version="INFORM Mid 2026").lookup("VNM")

    assert result is not None
    assert result.context_role == "baseline_vulnerability"
    assert result.vintage == 2026
    assert "not event impact" in result.interpretation.casefold()
