export function projectionSummary(prediction, lead) {
  const step = prediction?.projections?.find((candidate) => candidate.lead === lead);
  if (!step) return null;

  const annual = prediction.period_unit === 'financial_year';
  const period = annual && step.financial_year
    ? 'FY ' + step.financial_year
    : annual ? 'Financial-year step ' + lead : 'Sample months ' + (lead - 5) + '–' + lead;
  const units = annual ? 'dwelling fires' : 'sample incidents';
  const uncertainty = prediction.interval_status === 'withheld_after_evaluation'
    ? 'Prediction interval unavailable'
    : step.lower != null && step.upper != null
      ? 'Residual range ' + step.lower + '–' + step.upper
      : '';
  return { step, period, units, uncertainty };
}

export function forecastReleaseDescription(prediction) {
  const release = prediction?.forecast_release;
  if (!release) return '';
  const { observation_source: source, boundary, model, issue_date } = release;
  return source.label + ' · ' + source.method + ' (' + boundary.edition + ')'
    + ' · Observations through FY ' + source.last_financial_year
    + ' · Model ' + model.id + ' v' + model.version + ' · Issued ' + issue_date;
}
