"""Local course grading model and credit-weighted GPA estimates."""
from contextlib import contextmanager
import math
from pathlib import Path
import sqlite3
import time
import uuid

from annie.config import DATA_DIR

GPA_DB_PATH = Path(DATA_DIR) / 'gpa_tracker.sqlite3'

# NU undergraduate common grading scale. The tracker estimates a letter from
# percentages; the instructor and Registrar remain authoritative.
# https://registrar.nu.edu.kz/node/65
GRADE_SCALE = (
    ('A', 95.0, 4.00), ('A-', 90.0, 3.67), ('B+', 85.0, 3.33),
    ('B', 80.0, 3.00), ('B-', 75.0, 2.67), ('C+', 70.0, 2.33),
    ('C', 65.0, 2.00), ('C-', 60.0, 1.67), ('D+', 55.0, 1.33),
    ('D', 50.0, 1.00), ('F', 0.0, 0.00),
)


def letter_for_percent(value):
    value = max(0.0, min(100.0, float(value)))
    return next((letter, points) for letter, minimum, points in GRADE_SCALE
                if value >= minimum)


def _name(value, what='name'):
    value = ' '.join(str(value or '').split())
    if not value or len(value) > 100:
        raise ValueError(f'Enter a {what} between 1 and 100 characters.')
    return value


def _number(value, minimum, maximum, what):
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{what} must be a number.') from None
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f'{what} must be between {minimum:g} and {maximum:g}.')
    return value


def parse_score(value):
    """Accept a percentage or earned/possible points; blank means not graded."""
    if value is None or isinstance(value, str) and value.strip().casefold() in ('', 'not graded', '—'):
        return None
    if isinstance(value, str):
        value = value.strip()
        if '/' in value:
            parts = value.split('/')
            if len(parts) != 2:
                raise ValueError('Use a percentage or earned/possible points, for example 7/10.')
            earned = _number(parts[0], 0, 1_000_000, 'Earned points')
            possible = _number(parts[1], .000001, 1_000_000, 'Possible points')
            return _number(earned / possible * 100, 0, 100, 'Score')
        value = value.removesuffix('%').strip()
    return _number(value, 0, 100, 'Score')


def _score_input(value, parsed):
    return '' if parsed is None else str(value).strip() if isinstance(value, str) and '/' in value else f'{parsed:g}%'


class GpaStore:
    def __init__(self, path=None):
        self.path = Path(path or GPA_DB_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS courses (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL,
                    name_key TEXT NOT NULL UNIQUE, credits REAL NOT NULL,
                    target_percent REAL NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS assessments (
                    id TEXT PRIMARY KEY,
                    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
                    name TEXT NOT NULL, weight REAL NOT NULL,
                    score REAL, position INTEGER NOT NULL);
                CREATE INDEX IF NOT EXISTS assessment_course
                    ON assessments(course_id, position);
            ''')
            columns = {row['name'] for row in db.execute('PRAGMA table_info(assessments)')}
            if 'score_input' not in columns:
                db.execute("ALTER TABLE assessments ADD COLUMN score_input TEXT NOT NULL DEFAULT ''")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(str(self.path), timeout=5)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _course(db, course_id):
        row = db.execute('SELECT * FROM courses WHERE id=?', (course_id,)).fetchone()
        if not row:
            raise ValueError('Course was not found.')
        return dict(row)

    def courses(self):
        with self.connection() as db:
            return [dict(row) for row in db.execute('SELECT * FROM courses ORDER BY name_key')]

    def add_course(self, name, credits=5, target_percent=85, now=None):
        name = _name(name, 'course name')
        credits = _number(credits, .5, 30, 'Credits')
        target = _number(target_percent, 50, 100, 'Target percentage')
        try:
            with self.connection() as db:
                course_id = uuid.uuid4().hex
                db.execute('INSERT INTO courses VALUES (?,?,?,?,?,?)',
                           (course_id, name, name.casefold(), credits, target,
                            time.time() if now is None else now))
                return self._course(db, course_id)
        except sqlite3.IntegrityError:
            raise ValueError('A course with this name already exists.') from None

    def update_course(self, course_id, name, credits, target_percent, now=None):
        name = _name(name, 'course name')
        credits = _number(credits, .5, 30, 'Credits')
        target = _number(target_percent, 50, 100, 'Target percentage')
        try:
            with self.connection() as db:
                self._course(db, course_id)
                db.execute('''UPDATE courses SET name=?,name_key=?,credits=?,
                              target_percent=?,updated=? WHERE id=?''',
                           (name, name.casefold(), credits, target,
                            time.time() if now is None else now, course_id))
                return self._course(db, course_id)
        except sqlite3.IntegrityError:
            raise ValueError('A course with this name already exists.') from None

    def delete_course(self, course_id):
        with self.connection() as db:
            self._course(db, course_id)
            db.execute('DELETE FROM courses WHERE id=?', (course_id,))

    def assessments(self, course_id):
        with self.connection() as db:
            self._course(db, course_id)
            return [dict(row) for row in db.execute(
                'SELECT * FROM assessments WHERE course_id=? ORDER BY position,id',
                (course_id,))]

    @staticmethod
    def _assessment_values(name, weight, score):
        name = _name(name, 'component name')
        weight = _number(weight, .01, 100, 'Weight')
        score = parse_score(score)
        return name, weight, score

    @staticmethod
    def _check_total(db, course_id, weight, excluding=None):
        query = 'SELECT COALESCE(SUM(weight),0) FROM assessments WHERE course_id=?'
        args = [course_id]
        if excluding:
            query += ' AND id<>?'
            args.append(excluding)
        total = db.execute(query, args).fetchone()[0] + weight
        if total > 100.000001:
            raise ValueError(f'Component weights cannot exceed 100%. Current result would be {total:g}%.')

    def add_assessment(self, course_id, name, weight, score=None):
        entered = score
        name, weight, score = self._assessment_values(name, weight, score)
        with self.connection() as db:
            self._course(db, course_id)
            self._check_total(db, course_id, weight)
            position = db.execute(
                'SELECT COALESCE(MAX(position),-1)+1 FROM assessments WHERE course_id=?',
                (course_id,)).fetchone()[0]
            item_id = uuid.uuid4().hex
            db.execute('''INSERT INTO assessments (id,course_id,name,weight,score,position,score_input)
                          VALUES (?,?,?,?,?,?,?)''',
                       (item_id, course_id, name, weight, score, position, _score_input(entered, score)))
            return dict(db.execute('SELECT * FROM assessments WHERE id=?',
                                   (item_id,)).fetchone())

    def update_assessment(self, item_id, name, weight, score=None):
        entered = score
        name, weight, score = self._assessment_values(name, weight, score)
        with self.connection() as db:
            row = db.execute('SELECT * FROM assessments WHERE id=?', (item_id,)).fetchone()
            if not row:
                raise ValueError('Grade component was not found.')
            self._check_total(db, row['course_id'], weight, item_id)
            db.execute('UPDATE assessments SET name=?,weight=?,score=?,score_input=? WHERE id=?',
                       (name, weight, score, _score_input(entered, score), item_id))

    def set_score(self, item_id, value):
        score = parse_score(value)
        with self.connection() as db:
            changed = db.execute('UPDATE assessments SET score=?,score_input=? WHERE id=?',
                                 (score, _score_input(value, score), item_id)).rowcount
            if not changed:
                raise ValueError('Grade component was not found.')
        return score

    def what_if(self, course_id, remaining_score=80):
        """Project a final percentage without writing hypothetical grades."""
        score = _number(remaining_score, 0, 100, 'Hypothetical remaining average')
        current = self.summary(course_id)
        projected = current['earned_points'] + current['remaining_weight'] * score / 100
        letter, points = letter_for_percent(projected)
        return {'projected_percent': projected, 'projected_letter': letter,
                'projected_gpa_points': points, 'remaining_score': score,
                'remaining_weight': current['remaining_weight'],
                'unconfigured_weight': max(0, 100 - current['total_weight']),
                'target_reached': projected >= current['target_percent']}

    def delete_assessment(self, item_id):
        with self.connection() as db:
            changed = db.execute('DELETE FROM assessments WHERE id=?', (item_id,)).rowcount
            if not changed:
                raise ValueError('Grade component was not found.')

    def summary(self, course_id):
        with self.connection() as db:
            course = self._course(db, course_id)
            items = [dict(row) for row in db.execute(
                'SELECT * FROM assessments WHERE course_id=? ORDER BY position,id',
                (course_id,))]
        total_weight = sum(item['weight'] for item in items)
        graded = [item for item in items if item['score'] is not None]
        graded_weight = sum(item['weight'] for item in graded)
        earned = sum(item['weight'] * item['score'] / 100 for item in graded)
        current = earned / graded_weight * 100 if graded_weight else None
        remaining = max(0.0, 100.0 - graded_weight)
        required = ((course['target_percent'] - earned) / remaining * 100
                    if remaining else None)
        letter, points = letter_for_percent(current or 0)
        target_letter, target_points = letter_for_percent(course['target_percent'])
        return {**course, 'items': items, 'total_weight': total_weight,
                'graded_weight': graded_weight, 'earned_points': earned,
                'current_percent': current, 'current_letter': letter if current is not None else None,
                'current_gpa_points': points if current is not None else None,
                'remaining_weight': remaining, 'required_percent': required,
                'unconfigured_weight': max(0, 100 - total_weight),
                'target_letter': target_letter, 'target_gpa_points': target_points}

    def semester_summary(self):
        summaries = [self.summary(course['id']) for course in self.courses()]
        estimated = [item for item in summaries if item['current_percent'] is not None]
        credits = sum(item['credits'] for item in summaries)
        graded_credits = sum(item['credits'] for item in estimated)
        gpa = (sum(item['credits'] * item['current_gpa_points'] for item in estimated)
               / graded_credits if graded_credits else None)
        target_gpa = (sum(item['credits'] * item['target_gpa_points'] for item in summaries)
                      / credits if credits else None)
        return {'courses': len(summaries), 'credits': credits,
                'estimated_courses': len(estimated), 'estimated_credits': graded_credits,
                'estimated_gpa': gpa, 'target_gpa': target_gpa}
