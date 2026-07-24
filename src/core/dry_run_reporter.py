"""DryRunReporter — يولّد تقرير HTML لخطة محاكاة

يأخذ DryRunPlan ويُنتج ملف HTML قابل للفتح في المتصفح:
  - جدول ملخص بإحصائيات الإجراءات
  - جدول تفصيلي بكل إجراء مخطّط (اسم القاعدة، الملف، الإجراء، الوجهة)
  - جدول الملفات المتخطاة (مع السبب)
  - أزرار "تأكيد التنفيذ" و"إلغاء" (للعرض فقط — لا JS فعلي)
  - تنسيق نظيف بدون اعتماديات خارجية (inline CSS)

PR-05 من development-roadmap-v1.0 (IFM Phase A)
"""
from __future__ import annotations

import html
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

from .rule_schemas import DryRunPlan, PlannedAction, ActionType

logger = logging.getLogger(__name__)


# ─── Inline CSS ───────────────────────────────────────────────────────────

_CSS = """
:root {
  --bg: #f7f8fa;
  --card: #ffffff;
  --text: #1f2328;
  --muted: #656d76;
  --border: #d0d7de;
  --accent: #0969da;
  --warn: #d1242f;
  --ok: #1a7f37;
  --warn-bg: #ffebe9;
  --ok-bg: #dafbe1;
}
* { box-sizing: border-box; }
body {
  font-family: -apple-system, "Segoe UI", "Noto Sans", "Noto Sans SC", sans-serif;
  background: var(--bg);
  color: var(--text);
  margin: 0;
  padding: 24px;
  line-height: 1.6;
}
.container { max-width: 1200px; margin: 0 auto; }
h1, h2, h3 { color: var(--text); margin-top: 0; }
h1 { font-size: 24px; border-bottom: 1px solid var(--border); padding-bottom: 8px; }
h2 { font-size: 18px; margin-top: 28px; }
.card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 16px 20px;
  margin-bottom: 16px;
}
.summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px;
  margin-bottom: 8px;
}
.stat {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 12px 16px;
}
.stat .label { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; }
.stat .value { font-size: 24px; font-weight: 600; color: var(--text); }
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  background: var(--card);
  border-radius: 6px;
  overflow: hidden;
}
th, td { padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--border); }
th { background: #f3f4f6; font-weight: 600; color: var(--text); }
td { color: var(--text); }
tr:hover { background: #f9fafb; }
td.action-move { color: var(--accent); font-weight: 500; }
td.action-copy { color: #6f42c1; font-weight: 500; }
td.action-tag { color: var(--ok); font-weight: 500; }
td.action-untag { color: #b08800; font-weight: 500; }
td.action-set_category { color: #1f6feb; font-weight: 500; }
td.action-delete_flag { color: var(--warn); font-weight: 600; background: var(--warn-bg); }
.badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 500;
  background: #eaeef2;
  color: var(--text);
}
.badge-warn { background: var(--warn-bg); color: var(--warn); }
.badge-ok { background: var(--ok-bg); color: var(--ok); }
.muted { color: var(--muted); font-size: 12px; }
.warn-banner {
  background: var(--warn-bg);
  border: 1px solid var(--warn);
  border-radius: 6px;
  padding: 12px 16px;
  color: var(--warn);
  font-weight: 500;
  margin-bottom: 16px;
}
.path { font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 12px; word-break: break-all; }
.actions { margin-top: 20px; display: flex; gap: 12px; }
.btn {
  display: inline-block;
  padding: 10px 20px;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 500;
  text-decoration: none;
  border: 1px solid transparent;
}
.btn-primary { background: var(--ok); color: white; }
.btn-secondary { background: var(--card); color: var(--text); border-color: var(--border); }
.footer { margin-top: 32px; padding-top: 16px; border-top: 1px solid var(--border); color: var(--muted); font-size: 12px; }
"""


def _action_type_class(action_type: str) -> str:
    """فئة CSS للون الإجراء"""
    return f"action-{action_type}"


def _action_label(action_type: str) -> str:
    """تسمية الإجراء بالعربية"""
    labels = {
        ActionType.MOVE.value: "نقل",
        ActionType.COPY.value: "نسخ",
        ActionType.TAG.value: "وسم",
        ActionType.UNTAG.value: "إزالة وسم",
        ActionType.SET_CATEGORY.value: "ضبط تصنيف",
        ActionType.DELETE_FLAG.value: "وسم للحذف",
    }
    return labels.get(action_type, action_type)


def _action_description(planned: PlannedAction) -> str:
    """وصف نصي للإجراء"""
    a = planned.action
    if a.type in (ActionType.MOVE.value, ActionType.COPY.value):
        return f"← {planned.target_path or a.target}"
    if a.type in (ActionType.TAG.value, ActionType.UNTAG.value):
        return a.value or ""
    if a.type == ActionType.SET_CATEGORY.value:
        return a.value or ""
    if a.type == ActionType.DELETE_FLAG.value:
        return "يضع وسم to_delete (لا حذف فعلي)"
    return str(a)


def generate_html_report(
    plan: DryRunPlan,
    *,
    output_path: Optional[Union[str, Path]] = None,
    title: str = "تقرير المحاكاة (Dry-Run)",
) -> str:
    """يولّد تقرير HTML لخطة محاكاة

    Args:
        plan: خطة المحاكاة
        output_path: مسار الحفظ (إن None، يُرجع HTML فقط دون حفظ)
        title: عنوان التقرير

    Returns:
        سلسلة HTML الكاملة
    """
    summary = plan.summary
    action_counts = plan.action_type_counts()
    has_destructive = ActionType.DELETE_FLAG.value in action_counts
    generated_at = datetime.now().isoformat(timespec="seconds")

    # ─── ملخص إحصائي ───
    stats_html = []
    stats_html.append('<div class="stat"><div class="label">إجراءات</div>'
                      f'<div class="value">{plan.total_actions}</div></div>')
    stats_html.append('<div class="stat"><div class="label">ملفات متأثرة</div>'
                      f'<div class="value">{plan.files_affected}</div></div>')
    stats_html.append('<div class="stat"><div class="label">ملفات متخطاة</div>'
                      f'<div class="value">{len(plan.skipped_files)}</div></div>')
    stats_html.append('<div class="stat"><div class="label">قواعد مطبَّقة</div>'
                      f'<div class="value">{summary.get("ruleset_name", "—")}</div></div>')

    # ─── توزيع الإجراءات حسب النوع ───
    type_rows = []
    for action_type, count in sorted(action_counts.items()):
        cls = _action_type_class(action_type)
        label = _action_label(action_type)
        type_rows.append(
            f'<tr><td class="{cls}">{label}</td><td>{count}</td></tr>'
        )

    # ─── جدول الإجراءات التفصيلي ───
    action_rows = []
    for i, p in enumerate(plan.planned_actions, start=1):
        cls = _action_type_class(p.action.type)
        label = _action_label(p.action.type)
        desc = html.escape(_action_description(p))
        rule_name = html.escape(p.rule_name)
        file_name = html.escape(p.file_name)
        file_path = html.escape(p.file_path)
        action_rows.append(
            f'<tr>'
            f'<td>{i}</td>'
            f'<td>{rule_name}</td>'
            f'<td><div>{file_name}</div>'
            f'<div class="path muted">{file_path}</div></td>'
            f'<td class="{cls}">{label}</td>'
            f'<td class="path">{desc}</td>'
            f'</tr>'
        )

    # ─── جدول الملفات المتخطاة ───
    skipped_rows = []
    for s in plan.skipped_files:
        file_name = html.escape(s.get("file_name", ""))
        file_path = html.escape(s.get("file_path", ""))
        reason = html.escape(s.get("reason", ""))
        skipped_rows.append(
            f'<tr>'
            f'<td><div>{file_name}</div>'
            f'<div class="path muted">{file_path}</div></td>'
            f'<td class="muted">{reason}</td>'
            f'</tr>'
        )

    # ─── بناء HTML ───
    parts = []
    parts.append('<!DOCTYPE html>')
    parts.append('<html lang="ar" dir="rtl">')
    parts.append('<head>')
    parts.append('<meta charset="UTF-8">')
    parts.append('<meta name="viewport" content="width=device-width, initial-scale=1.0">')
    parts.append(f'<title>{html.escape(title)}</title>')
    parts.append(f'<style>{_CSS}</style>')
    parts.append('</head>')
    parts.append('<body>')
    parts.append('<div class="container">')

    # عنوان
    parts.append(f'<h1>{html.escape(title)}</h1>')
    parts.append(f'<p class="muted">قاعدة البيانات: <code>{html.escape(plan.base_dir or "—")}</code> '
                 f'· وُلِّد في: <code>{generated_at}</code></p>')

    # تنبيه تدميري
    if has_destructive:
        parts.append('<div class="warn-banner">⚠️ تحتوي الخطة على إجراءات تدميرية '
                     '(وسم للحذف). لن تُنفَّذ إلا بتأكيد صريح '
                     '(<code>confirm_destructive=True</code>).</div>')

    # ملخص
    parts.append('<h2>الملخص</h2>')
    parts.append('<div class="summary-grid">')
    parts.extend(stats_html)
    parts.append('</div>')

    # توزيع الإجراءات
    if type_rows:
        parts.append('<div class="card">')
        parts.append('<h2>توزيع الإجراءات حسب النوع</h2>')
        parts.append('<table><thead><tr><th>النوع</th><th>العدد</th></tr></thead>')
        parts.append('<tbody>')
        parts.extend(type_rows)
        parts.append('</tbody></table>')
        parts.append('</div>')

    # جدول الإجراءات
    if action_rows:
        parts.append('<div class="card">')
        parts.append(f'<h2>الإجراءات المخطّطة ({plan.total_actions})</h2>')
        parts.append('<table><thead><tr>'
                     '<th>#</th><th>القاعدة</th><th>الملف</th>'
                     '<th>الإجراء</th><th>التفاصيل</th>'
                     '</tr></thead><tbody>')
        parts.extend(action_rows)
        parts.append('</tbody></table>')
        parts.append('</div>')

    # الملفات المتخطاة
    if skipped_rows:
        parts.append('<div class="card">')
        parts.append(f'<h2>الملفات المتخطاة ({len(plan.skipped_files)})</h2>')
        parts.append('<table><thead><tr><th>الملف</th><th>السبب</th></tr></thead><tbody>')
        parts.extend(skipped_rows)
        parts.append('</tbody></table>')
        parts.append('</div>')

    # أزرار
    parts.append('<div class="actions">')
    parts.append('<span class="btn btn-primary">تأكيد التنفيذ</span>')
    parts.append('<span class="btn btn-secondary">إلغاء</span>')
    parts.append('</div>')

    # تذييل
    parts.append('<div class="footer">')
    parts.append('IFM Rule Engine · Dry-Run Report · '
                 'هذا التقرير لا يُعدِّل أي ملف. استخدم <code>RuleEngine.execute()</code> '
                 'لتطبيق الإجراءات مع تسجيل التراجع.')
    parts.append('</div>')

    parts.append('</div>')  # container
    parts.append('</body></html>')

    html_str = "\n".join(parts)

    if output_path is not None:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html_str, encoding="utf-8")
        logger.info(f"كُتب تقرير المحاكاة إلى {out} ({len(html_str)} bytes)")

    return html_str


def save_report(plan: DryRunPlan, output_path: Union[str, Path]) -> Path:
    """واجهة مختصرة: يحفظ التقرير ويُرجع المسار"""
    p = Path(output_path)
    generate_html_report(plan, output_path=p)
    return p
