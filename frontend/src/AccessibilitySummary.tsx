import { digits, duration } from './api';
import type { ResultRow } from './api';

const statusLabels: Record<string, string> = {
  not_evaluated: 'هنوز محاسبه نشده', queued: 'در صف محاسبه', running: 'در حال محاسبه',
  timeout: 'مهلت محاسبهٔ مسیر تمام شد', api_error: 'سرویس مسیر پاسخ نداد', invalid_response: 'پاسخ مسیر معتبر نبود',
  no_route_returned: 'مسیر قابل استفاده‌ای برنگشت', no_feasible_returned_itinerary: 'در مسیرهای بازگشتی گزینهٔ منطبق پیدا نشد',
  out_of_coverage: 'خارج از پوشش تأییدشده', not_configured: 'سرویس مسیر آماده نیست',
  stops_unavailable: 'دادهٔ ایستگاه‌ها در دسترس نیست', no_stops: 'ایستگاه معتبری در دادهٔ موجود نیست',
  unknown: 'دسترسی نامعلوم', invalid_location: 'موقعیت ملک برای محاسبه نامعلوم است',
};

export default function AccessibilitySummary({ row }: { row: ResultRow }) {
  const evidence = row.accessibility;
  if (!evidence) return <p className="muted">دسترسی هنوز محاسبه نشده است.</p>;
  const stop = evidence.nearest_stop, walkingStop = evidence.walking_stop;
  const stopName = stop?.name_fa ?? stop?.name ?? 'ایستگاه حمل‌ونقل عمومی';
  const walkingName = walkingStop?.name_fa ?? walkingStop?.name ?? stopName;
  const status = evidence.status === 'ok' ? null : statusLabels[evidence.status] ?? 'محاسبهٔ مسیر کامل نیست';
  const route = row.selected_itinerary;
  return <div className="route-summary accessibility-summary" data-accessibility-mode={evidence.mode} data-accessibility-status={evidence.status}>
    {evidence.mode === 'nearby_stop' ? <>
      <strong>دسترسی به حمل‌ونقل عمومی</strong>
      <span>{stop ? `نزدیک‌ترین ایستگاه ${stop.stop_type === 'metro' ? 'مترو' : stop.stop_type === 'bus' ? 'اتوبوس' : ''}: ${stopName}` : 'ایستگاه نزدیک: نامعلوم'}</span>
      <span>فاصلهٔ مستقیم تا ایستگاه: {evidence.straight_line_meters === null ? 'نامعلوم' : `${digits(Math.round(evidence.straight_line_meters))} متر`}</span>
      <span>پیاده‌روی تا {walkingName}: {evidence.walk_distance_meters === null ? 'مسافت نامعلوم' : `${digits(Math.round(evidence.walk_distance_meters))} متر`} / {duration(evidence.walk_duration_seconds)}</span>
      {walkingStop && stop && (walkingStop.stop_id ?? walkingStop.id) !== (stop.stop_id ?? stop.id) && <small>ایستگاه منتخب مسیر پیاده با نزدیک‌ترین ایستگاه از نظر فاصلهٔ مستقیم متفاوت است.</small>}
    </> : <>
      <strong>سفر تا مقصد همیشگی: {duration(evidence.total_duration_seconds)}</strong>
      <span>کل پیاده‌روی: {duration(evidence.walk_duration_seconds)} · {evidence.walk_distance_meters === null ? 'مسافت نامعلوم' : `${digits(Math.round(evidence.walk_distance_meters))} متر`}</span>
      {evidence.effective_at && <small>زمان مبنای این مسیر: {new Date(evidence.effective_at).toLocaleString('fa-IR', { timeZone: 'Asia/Tehran' })} (تهران)</small>}
    </>}
    {status && <small>{status}؛ مقدار نامعلوم صفر نیست.</small>}
    {route?.schedule_basis === 'synthetic_schedule' && <small>برآورد مبتنی بر برنامهٔ فرضی</small>}
    {route?.source_kind === 'synthetic_fixture' && <small>مسیر ساختگی دمو</small>}
    {route?.source_kind === 'recorded_otp' && <small>پاسخ ذخیره‌شدهٔ OTP</small>}
    {route?.source_kind === 'live_otp' && <small>محاسبه‌شده با OTP؛ زمان محاسبه: {new Date(evidence.calculated_at ?? route.fetched_at).toLocaleString('fa-IR', { timeZone: 'Asia/Tehran' })}</small>}
  </div>;
}
