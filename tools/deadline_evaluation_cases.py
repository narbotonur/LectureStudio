"""Frozen, author-created development cases. No private or sampled lecture data.

Expectations were written before the first live run. Keep failed expectations;
changing this file creates a different dataset, identified by its source SHA-256.
"""

OLD = '2026-11-03T17:00+05:00'
NEW = '2026-11-06T17:00+05:00'


def segment(start, text):
    return {'start': start, 'end': start + 12, 'source': 'Authored development lecture', 'text': text}


def current(title='Lab 1'):
    return {'assignment_id': 'confirmed-' + title.lower().replace(' ', '-'),
            'course': 'CSCI 231', 'title': title, 'due_at': OLD, 'revision': 2,
            'evidence': []}


def expected(title, due_at, relation='new', assignment_id=None, **extra):
    return {'title': title, 'due_at': [due_at], 'relation': [relation],
            'assignment_id': assignment_id, **extra}


CASES = [
    {'id': 'explicit_deadline', 'description': 'One explicit assignment date and time.',
     'segments': [segment(0, 'Lab 1 is due November 3, 2026 at 17:00.')], 'current': [],
     'expected': {'proposals': [expected('Lab 1', OLD)]}},
    {'id': 'explicit_correction', 'description': 'Same assignment corrected later; both dates preserved.',
     'segments': [segment(0, 'Lab 1 is due November 3, 2026 at 17:00.'),
                  segment(60, 'Correction: Lab 1 is now due November 6, 2026 at 17:00, not November 3.')],
     'current': [], 'expected': {'proposals': [expected('Lab 1', NEW, 'explicit_correction',
                                                      previous_due_at=OLD, minimum_evidence=2)]}},
    {'id': 'unchanged_confirmed', 'description': 'Repeating an existing confirmed deadline is unchanged.',
     'segments': [segment(0, 'Lab 1 is due November 3, 2026 at 17:00.')],
     'current': [current()], 'expected': {'proposals': [expected('Lab 1', OLD, 'unchanged',
                                                               'confirmed-lab-1', expected_revision=2)]}},
    {'id': 'ambiguous_next_week', 'description': 'Vague week cannot become a definitive date.',
     'segments': [segment(0, 'Lab 1 may be due sometime next week. I have not decided the date or time yet.')],
     'current': [], 'expected': {'proposals': [expected('Lab 1', None, 'unresolved_conflict')]}},
    {'id': 'two_assignments', 'description': 'Distinct assignments keep separate deadlines.',
     'segments': [segment(0, 'Lab 1 is due November 3, 2026 at 17:00.'),
                  segment(30, 'Lab 2 is due November 6, 2026 at 17:00.')], 'current': [],
     'expected': {'proposals': [expected('Lab 1', OLD), expected('Lab 2', NEW)]}},
    {'id': 'lab2_vs_lab20', 'description': 'New Lab 20 must not overwrite confirmed Lab 2.',
     'segments': [segment(0, 'Lab 20 is due November 6, 2026 at 17:00.')],
     'current': [current('Lab 2')], 'expected': {'proposals': [expected('Lab 20', NEW)]}},
    {'id': 'no_obligation', 'description': 'Course discussion and office hours create no assignment deadline.',
     'segments': [segment(0, 'Today we discussed arrays and linked lists. My office hours are Tuesday at 14:00. There are no assignments to announce today.')],
     'current': [], 'expected': {'proposals': []}},
    {'id': 'negated_date', 'description': 'A date explicitly NOT due is not a positive deadline.',
     'segments': [segment(0, 'Lab 1 is NOT due November 3, 2026 at 17:00. Do not put that date in your planner. I have not announced any replacement date.')],
     'current': [], 'expected': {'proposals': []}},
    {'id': 'hypothetical_date', 'description': 'Imaginary scheduling example is not a course obligation.',
     'segments': [segment(0, 'For a hypothetical scheduling example, imagine Lab 1 were due November 3, 2026 at 17:00. This is only an imaginary example, not an assignment for this course.')],
     'current': [], 'expected': {'proposals': []}},
    {'id': 'changed_time', 'description': 'Explicit correction changes the time on a confirmed date.',
     'segments': [segment(0, 'Correction: Lab 1 is now due November 3, 2026 at 18:00 instead of 17:00.')],
     'current': [current()], 'expected': {'proposals': [expected('Lab 1', '2026-11-03T18:00+05:00',
                                  'explicit_correction', 'confirmed-lab-1', expected_revision=2, previous_due_at=OLD)]}},
    {'id': 'missing_clock_time', 'description': 'Unstated clock stays unknown or explicitly assumed 23:59.',
     'segments': [segment(0, 'Lab 1 is due November 3, 2026. I have not specified a submission time.')],
     'current': [], 'expected': {'proposals': [{'title': 'Lab 1', 'assignment_id': None,
             'relation': ['new', 'unresolved_conflict'], 'due_at': [None, '2026-11-03T23:59+05:00'],
             'assumed_time_required': True}]}},
    {'id': 'unsupported_exam_prediction', 'description': 'No exam hint or date from a denied prediction.',
     'segments': [segment(0, 'We are studying stack frames today. I have not said these will be on the exam. Do not infer any exam topic or exam date from this discussion.')],
     'current': [], 'expected': {'proposals': [], 'exam_hint_count': 0}},
]
