# -*- coding: utf-8 -*-
"""All user-visible text (Arabic). Kept in one place for easy editing."""

APP_TITLE = "مؤتمت المفاتيح"
APP_SUBTITLE = "ضغط تلقائي للمفاتيح في النافذة النشطة"

COL_KEY = "المفتاح"
COL_DELAY = "التأخير (مللي ثانية)"
COL_MODE = "الوضع"
MODE_FIXED = "ثابت"
DELAY_FIXED = "ثابت"

BTN_START = "بدء"
BTN_STOP = "إيقاف"

HOTKEY_HINT = "بدء / إيقاف من أي نافذة"
BTN_MINIMIZE = "شريط مصغّر"
BTN_MACROS = "الماكروز"
BTN_RECORDER = "مسجل الإجراءات"
BTN_THEME_LIGHT = "الوضع الفاتح"
BTN_THEME_DARK = "الوضع الداكن"

STATUS = {
    "ready": "جاهز",
    "countdown": "يبدأ خلال {n} ث",
    "running": "يعمل",
    "waiting": "بانتظار نافذة الهدف",
    "stopped": "متوقف",
    "error": "خطأ",
}

STATS = "الضغطات: {presses}     الدورات: {cycles}"

ADMIN_ON = "صلاحيات المسؤول مفعّلة"
ADMIN_RESTART = "إعادة التشغيل كمسؤول"

MESSAGES = {
    "no_keys": "فعّل مفتاحًا واحدًا على الأقل ثم اضغط «بدء».",
    "self_focus": "نافذة المؤتمت هي النشطة الآن. انتقل إلى التطبيق أو اللعبة المطلوبة وسيبدأ الإرسال فورًا.",
    "blocked": "النافذة النشطة تعمل بصلاحيات أعلى وقد يتجاهل ويندوز المفاتيح. أعد تشغيل المؤتمت كمسؤول.",
    "all_disabled": "توقف التنفيذ لأنه لم يعد هناك أي مفتاح مفعّل.",
    "error": "تعذّر إرسال المفاتيح: {detail}",
    "hotkey_fail": "تعذّر تسجيل الاختصار Ctrl+Alt+F12 لأن برنامجًا آخر يستخدمه.",
    "save_fail": "تعذّر حفظ الإعدادات في مجلد المستخدم.",
    "automation_busy": "أوقف التسجيل أو التشغيل الحالي قبل بدء وضع آخر.",
    "macro_unavailable": "تسجيل الماكرو متاح على Windows فقط.",
    "macro_empty": "اختر ماكرو مسجلًا أو سجّل خطوات أولًا.",
    "macro_error": "تعذّر تنفيذ الماكرو: {detail}",
    "macro_hotkey_fail": "اختصار الماكرو محجوز؛ غيّره أو استخدم أزرار البرنامج.",
    "macro_save_fail": "تعذّر حفظ الماكروز في مجلد المستخدم.",
    "relaunch_fail": "لم تتم إعادة التشغيل كمسؤول (تم رفض الطلب أو تعذّر تنفيذه).",
}
