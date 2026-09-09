import calendar,re
from datetime import date,timedelta
from rest_framework.exceptions import ValidationError

def report_dates(message,today):
    """Deterministic English date resolution; ambiguous queries fail closed."""
    q=message.lower()
    iso=re.findall(r'\b\d{4}-\d{2}-\d{2}\b',q)
    try:
        if re.search(r'\b(q[1-4]|quarter|week|today|yesterday|ytd)\b|year.to.date',q): raise ValueError()
        named=[(i,name) for i,name in enumerate(calendar.month_name) if name and re.search(r'\b'+name.lower()+r'\b',q)]
        relative=[term for term in ('last month','this month','last year','this year') if term in q]
        years=re.findall(r'\b(?:19|20|21)\d{2}\b',q)
        if len(relative)>1 or (relative and (iso or years)) or len(named)>1: raise ValueError()
        if len(iso)==2: start,end=map(date.fromisoformat,iso)
        elif len(iso)==1: start=end=date.fromisoformat(iso[0])
        elif 'last month' in q or 'this month' in q:
            if named: raise ValueError()
            current=today.replace(day=1)
            anchor=current-timedelta(days=1) if 'last month' in q else current
            start=anchor.replace(day=1); end=date(anchor.year,anchor.month,calendar.monthrange(anchor.year,anchor.month)[1])
        elif 'last year' in q or 'this year' in q:
            year=today.year-(1 if 'last year' in q else 0); start=date(year,1,1); end=date(year,12,31)
            if named:
                month=named[0][0]; start=date(year,month,1); end=date(year,month,calendar.monthrange(year,month)[1])
        else:
            matches=list(re.finditer(r'\b(\d{4})-(\d{2})\b',q))
            if len(matches)>1: raise ValueError()
            match=matches[0] if matches else None
            if named and re.search(r'\b\d{1,2}(?:st|nd|rd|th)?\b',q): raise ValueError()
            if match: year,month=map(int,match.groups())
            elif len(named)==1 and len(years)==1: year,month=int(years[0]),named[0][0]
            elif len(years)==1 and not named:
                start=date(int(years[0]),1,1); end=date(int(years[0]),12,31)
                return start,end
            else: raise ValueError()
            start=date(year,month,1); end=date(year,month,calendar.monthrange(year,month)[1])
        if end<start or (end-start).days>3660: raise ValueError()
        return start,end
    except (ValueError,OverflowError):
        raise ValidationError('Specify a month and year (September 2026), a year (2026), this/last month/year, or two ISO dates (2026-09-01 to 2026-09-30). Dates are inclusive and use the clinic timezone.')
