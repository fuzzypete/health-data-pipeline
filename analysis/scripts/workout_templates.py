#!/usr/bin/env python3
"""
Structured workout templates with sets, reps, rest, and supersets.

Provides detailed workout structures for the weekly training planner,
designed for 40-45 minute sessions with time for cardio, core, and mobility.

Exercise pools enable rotation for variety and balanced muscle development.
Exercises selected based on:
- EMG activation studies
- Stretch-mediated hypertrophy research
- Equipment availability (dumbbells, pull-up/dip station, bench)
- Shoulder impingement considerations (no bilateral overhead press)
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class ExerciseOption:
    """An exercise option within a pool."""
    name: str  # Must match JEFIT exercise name
    evidence_notes: str = ""  # Why this exercise is included
    shoulder_safe: bool = True  # Flag for impingement-prone individuals


@dataclass
class ExercisePool:
    """Pool of exercises for a movement pattern, enabling rotation."""
    movement_pattern: str  # e.g., "Horizontal Push", "Vertical Pull"
    muscle_groups: list[str]  # Primary muscles targeted
    options: list[ExerciseOption]

    def get_rotation(self, week_number: int, count: int = 1) -> list[str]:
        """Get exercise(s) for this week based on rotation."""
        safe_options = [o for o in self.options if o.shoulder_safe]
        if not safe_options:
            safe_options = self.options

        start_idx = week_number % len(safe_options)
        selected = []
        for i in range(count):
            idx = (start_idx + i) % len(safe_options)
            selected.append(safe_options[idx].name)
        return selected


# =============================================================================
# EXERCISE POOLS (Evidence-Based Selection)
# =============================================================================

HORIZONTAL_PUSH = ExercisePool(
    movement_pattern="Horizontal Push",
    muscle_groups=["Chest", "Anterior Delt", "Triceps"],
    options=[
        ExerciseOption(
            name="Dumbbell Bench Press",
            evidence_notes="Gold standard for chest. DB allows natural shoulder path, full ROM."
        ),
        ExerciseOption(
            name="Dumbbell Incline Bench Press",
            evidence_notes="Higher clavicular (upper) chest activation at 30-45° incline."
        ),
        ExerciseOption(
            name="Dumbbell Fly",
            evidence_notes="Stretch-mediated hypertrophy. Peak tension in stretched position."
        ),
        ExerciseOption(
            name="Weighted Tricep Dip",
            evidence_notes="Heavy compound. High chest/tricep activation. Monitor shoulder comfort."
        ),
    ],
)

VERTICAL_PUSH = ExercisePool(
    movement_pattern="Vertical Push",
    muscle_groups=["Anterior Delt", "Lateral Delt", "Triceps"],
    options=[
        ExerciseOption(
            name="Dumbbell One-Arm Press (Palms In)",
            evidence_notes="Shoulder-safe overhead pattern. Allows scapular freedom. Half-kneeling variant preferred."
        ),
        ExerciseOption(
            name="Dumbbell Shoulder Press",
            evidence_notes="Bilateral overhead. Higher load capacity but more impingement risk.",
            shoulder_safe=False  # Marked unsafe for impingement-prone
        ),
    ],
)

VERTICAL_PULL = ExercisePool(
    movement_pattern="Vertical Pull",
    muscle_groups=["Lats", "Biceps", "Rear Delt"],
    options=[
        ExerciseOption(
            name="Weighted Chin-Up",
            evidence_notes="Supinated grip = higher bicep activation + lat stretch. Gold standard."
        ),
        ExerciseOption(
            name="Chin-Up",
            evidence_notes="Bodyweight variant. Good for higher rep work or deload."
        ),
        ExerciseOption(
            name="Weighted Pull-Up",
            evidence_notes="Pronated grip = more lat emphasis, less bicep. Good rotation option."
        ),
        ExerciseOption(
            name="Pull-Up",
            evidence_notes="Bodyweight wide grip. Lat width focus."
        ),
    ],
)

HORIZONTAL_PULL = ExercisePool(
    movement_pattern="Horizontal Pull",
    muscle_groups=["Rhomboids", "Mid-Traps", "Lats", "Rear Delt", "Biceps"],
    options=[
        ExerciseOption(
            name="Dumbbell Bent-Over Row",
            evidence_notes="Bilateral row. High lat/rhomboid EMG. Strengthens posterior shoulder."
        ),
        ExerciseOption(
            name="Dumbbell One-Arm Row",
            evidence_notes="Unilateral. Allows torso rotation, longer ROM. Anti-rotation core benefit."
        ),
        ExerciseOption(
            name="Dumbbell Reverse Fly",
            evidence_notes="Rear delt isolation. Important for shoulder balance/health."
        ),
    ],
)

LATERAL_DELT = ExercisePool(
    movement_pattern="Lateral Raise",
    muscle_groups=["Lateral Delt"],
    options=[
        ExerciseOption(
            name="Dumbbell Lateral Raise",
            evidence_notes="Standard lateral delt isolation. Keep below 90° for shoulder safety."
        ),
        ExerciseOption(
            name="Dumbbell Lateral Raise (Prone)",
            evidence_notes="Rear delt / posterior lateral delt emphasis. Shoulder-friendly."
        ),
    ],
)

QUAD_DOMINANT = ExercisePool(
    movement_pattern="Quad Dominant",
    muscle_groups=["Quads", "Glutes"],
    options=[
        ExerciseOption(
            name="Bulgarian Split Squat",
            evidence_notes="Unilateral. High quad activation, glute stretch. Fixes imbalances."
        ),
        ExerciseOption(
            name="Dumbbell Squat",
            evidence_notes="Bilateral. Limited by grip but good compound. Goblet position works too."
        ),
    ],
)

HIP_DOMINANT = ExercisePool(
    movement_pattern="Hip Hinge",
    muscle_groups=["Glutes", "Hamstrings"],
    options=[
        ExerciseOption(
            name="Barbell Hip Thrust",  # Actually belt-loaded DB
            evidence_notes="Highest glute EMG of any exercise (Contreras). Peak tension at lockout."
        ),
        ExerciseOption(
            name="Dumbbell Stiff-Leg Deadlift",
            evidence_notes="Hamstring stretch emphasis. RDL pattern."
        ),
        ExerciseOption(
            name="Kettlebell Single-Leg Deadlift",  # Actually DB
            evidence_notes="Unilateral hip hinge. Balance + glute/ham activation."
        ),
    ],
)

CALVES = ExercisePool(
    movement_pattern="Calf Raise",
    muscle_groups=["Gastrocnemius", "Soleus"],
    options=[
        ExerciseOption(
            name="Dumbbell Calf Raise",
            evidence_notes="Standing = gastrocnemius emphasis. Full ROM, pause at top."
        ),
    ],
)

TRICEPS = ExercisePool(
    movement_pattern="Tricep Isolation",
    muscle_groups=["Triceps"],
    options=[
        ExerciseOption(
            name="Weighted Tricep Dip",
            evidence_notes="Compound, heavy. All three heads."
        ),
        ExerciseOption(
            name="Dumbbell Tricep Extension (Supine)",
            evidence_notes="Long head emphasis (overhead/stretched position)."
        ),
        ExerciseOption(
            name="Dumbbell Tricep Extension",
            evidence_notes="Standing overhead extension. Long head stretch."
        ),
        ExerciseOption(
            name="Dumbbell Tricep Kickback",
            evidence_notes="Peak contraction focus. Lateral head emphasis."
        ),
    ],
)

BICEPS = ExercisePool(
    movement_pattern="Bicep Curl",
    muscle_groups=["Biceps", "Brachialis"],
    options=[
        ExerciseOption(
            name="Dumbbell Incline Curl",
            evidence_notes="Stretched position = more hypertrophy (Schoenfeld). Long head emphasis."
        ),
        ExerciseOption(
            name="Dumbbell One-Arm Preacher Curl",
            evidence_notes="Shortened position peak contraction. Short head emphasis. Your bench works for this."
        ),
        ExerciseOption(
            name="Dumbbell Hammer Curl",
            evidence_notes="Brachialis + brachioradialis. Neutral grip is shoulder-friendly."
        ),
        ExerciseOption(
            name="Dumbbell Seated Bicep Curl",
            evidence_notes="Standard curl. Eliminates momentum."
        ),
    ],
)

CORE_ANTI_LATERAL = ExercisePool(
    movement_pattern="Anti-Lateral Flexion",
    muscle_groups=["Obliques", "QL"],
    options=[
        ExerciseOption(
            name="Dumbbell Side Bend",
            evidence_notes="Loaded lateral flexion. Oblique strength."
        ),
        ExerciseOption(
            name="Side Bridge",
            evidence_notes="Isometric anti-lateral flexion. McGill-approved core stability."
        ),
    ],
)

CORE_ANTI_EXTENSION = ExercisePool(
    movement_pattern="Anti-Extension",
    muscle_groups=["Rectus Abdominis", "TVA"],
    options=[
        ExerciseOption(
            name="Plank",
            evidence_notes="Isometric anti-extension. Foundation core stability."
        ),
        ExerciseOption(
            name="Hollow Body Hold",
            evidence_notes="Gymnastic core. Posterior pelvic tilt hold."
        ),
        ExerciseOption(
            name="Barbell Ab Rollout",
            evidence_notes="Dynamic anti-extension. High rectus abdominis activation."
        ),
    ],
)

CORE_FLEXION = ExercisePool(
    movement_pattern="Spinal Flexion",
    muscle_groups=["Rectus Abdominis"],
    options=[
        ExerciseOption(
            name="Hanging Leg Raise",
            evidence_notes="Lower abs emphasis. Grip/lat engagement bonus."
        ),
        ExerciseOption(
            name="Decline Crunch",
            evidence_notes="Loaded crunch. Upper abs."
        ),
        ExerciseOption(
            name="Crunch",
            evidence_notes="Basic crunch. Higher reps."
        ),
    ],
)


# =============================================================================
# EXERCISE DATACLASS (for workout templates)
# =============================================================================

@dataclass
class Exercise:
    """Single exercise with programming details."""
    name: str
    sets: int
    reps: str  # e.g., "8-10" or "6-8"
    rest_sec: int  # Rest after this exercise (or after superset pair)
    superset_with: Optional[str] = None  # Name of exercise to superset with
    notes: str = ""


@dataclass
class WorkoutBlock:
    """A block of exercises (main lifts, accessories, etc.)."""
    name: str
    exercises: list[Exercise]
    notes: str = ""


@dataclass
class WorkoutTemplate:
    """Complete workout session template."""
    name: str  # e.g., "Upper A"
    focus: str  # e.g., "Push emphasis"
    blocks: list[WorkoutBlock]
    estimated_time_min: int
    warmup_notes: str = ""

    def get_exercise_names(self) -> list[str]:
        """Return all exercise names in this template."""
        names = []
        for block in self.blocks:
            for ex in block.exercises:
                names.append(ex.name)
        return names


@dataclass
class DayPlan:
    """Single day's training plan."""
    day: str  # e.g., "Monday"
    primary: str  # e.g., "Upper A"
    secondary: str  # e.g., "Core Circuit"
    cardio: str  # e.g., "Zone 2 - 30min bike"
    mobility: str  # e.g., "5min hip stretches"
    total_time_min: int
    notes: str = ""


# =============================================================================
# WORKOUT TEMPLATE BUILDER (uses pools for rotation)
# =============================================================================

def get_week_number() -> int:
    """Get current week number of the year for rotation."""
    return datetime.now().isocalendar()[1]


def build_upper_a(week: int = None) -> WorkoutTemplate:
    """
    Upper A: Horizontal focus with antagonist supersets.

    SS1: Horizontal push + Horizontal pull (bench/row)
    SS2: Chest isolation + Rear delt (fly/reverse fly)
    SS3: Tricep + Bicep
    """
    if week is None:
        week = get_week_number()

    # Rotate horizontal push: Bench → Incline
    h_push_options = ["Dumbbell Bench Press", "Dumbbell Incline Bench Press"]
    h_push = h_push_options[week % 2]

    # Rotate horizontal pull: Bent-Over → One-Arm
    h_pull_options = ["Dumbbell Bent-Over Row", "Dumbbell One-Arm Row"]
    h_pull = h_pull_options[week % 2]

    # Rotate tricep: Dip → Extension
    tricep_options = ["Weighted Tricep Dip", "Dumbbell Tricep Extension (Supine)"]
    tricep = tricep_options[week % 2]

    # Rotate bicep: Incline → Preacher → Hammer → Seated
    bicep = BICEPS.get_rotation(week)[0]

    return WorkoutTemplate(
        name="Upper A",
        focus="Horizontal focus (chest/back antagonist pairs)",
        estimated_time_min=42,
        warmup_notes="Band pull-aparts, arm circles, light DB press",
        blocks=[
            WorkoutBlock(
                name="Superset 1 - Horizontal Push/Pull",
                notes="Antagonist pairing, 60-90s after pair",
                exercises=[
                    Exercise(
                        name=h_push,
                        sets=3,
                        reps="6-8",
                        rest_sec=0,
                        superset_with=h_pull,
                        notes="Control descent, full ROM"
                    ),
                    Exercise(
                        name=h_pull,
                        sets=3,
                        reps="8-10",
                        rest_sec=90,
                        notes="Squeeze scapulae, control negative"
                    ),
                ],
            ),
            WorkoutBlock(
                name="Superset 2 - Chest/Rear Delt",
                notes="Isolation pairing, 60s after pair",
                exercises=[
                    Exercise(
                        name="Dumbbell Fly",
                        sets=3,
                        reps="10-12",
                        rest_sec=0,
                        superset_with="Dumbbell Reverse Fly",
                        notes="Stretch at bottom"
                    ),
                    Exercise(
                        name="Dumbbell Reverse Fly",
                        sets=3,
                        reps="12-15",
                        rest_sec=60,
                        notes="Rear delt focus, squeeze at top"
                    ),
                ],
            ),
            WorkoutBlock(
                name="Superset 3 - Tricep/Bicep",
                notes="Arm antagonist pairing, 60s after pair",
                exercises=[
                    Exercise(
                        name=tricep,
                        sets=2,
                        reps="8-10",
                        rest_sec=0,
                        superset_with=bicep,
                        notes="Full ROM"
                    ),
                    Exercise(
                        name=bicep,
                        sets=2,
                        reps="10-12",
                        rest_sec=60,
                        notes="Control negative"
                    ),
                ],
            ),
        ],
    )


def build_upper_b(week: int = None) -> WorkoutTemplate:
    """
    Upper B: Vertical focus with antagonist supersets.

    SS1: Vertical push + Vertical pull (press/chin-up)
    SS2: Lateral delt + Rear delt (lateral raise/prone raise)
    SS3: Tricep + Bicep
    """
    if week is None:
        week = get_week_number()

    # Vertical push: One-arm press only (shoulder-safe)
    v_push = "Dumbbell One-Arm Press (Palms In)"

    # Rotate vertical pull: Weighted Chin → Chin → Weighted Pull → Pull
    v_pull = VERTICAL_PULL.get_rotation(week)[0]

    # Rotate tricep: Extension → Dip (opposite of Upper A)
    tricep_options = ["Dumbbell Tricep Extension (Supine)", "Weighted Tricep Dip"]
    tricep = tricep_options[week % 2]

    # Rotate bicep: offset from Upper A by 2 positions
    bicep = BICEPS.get_rotation(week + 2)[0]

    return WorkoutTemplate(
        name="Upper B",
        focus="Vertical focus (shoulder/back antagonist pairs)",
        estimated_time_min=42,
        warmup_notes="Band pull-aparts, cat-cow, dead hangs",
        blocks=[
            WorkoutBlock(
                name="Superset 1 - Vertical Push/Pull",
                notes="Antagonist pairing, 90s after pair",
                exercises=[
                    Exercise(
                        name=v_push,
                        sets=3,
                        reps="8-10/arm",
                        rest_sec=0,
                        superset_with=v_pull,
                        notes="Half-kneeling, neutral grip"
                    ),
                    Exercise(
                        name=v_pull,
                        sets=3,
                        reps="5-8",
                        rest_sec=90,
                        notes="Full extension at bottom, chin over bar"
                    ),
                ],
            ),
            WorkoutBlock(
                name="Superset 2 - Lateral/Rear Delt",
                notes="Shoulder antagonist pairing, 60s after pair",
                exercises=[
                    Exercise(
                        name="Dumbbell Lateral Raise",
                        sets=3,
                        reps="12-15",
                        rest_sec=0,
                        superset_with="Dumbbell Lateral Raise (Prone)",
                        notes="Control negative, stay below 90°"
                    ),
                    Exercise(
                        name="Dumbbell Lateral Raise (Prone)",
                        sets=3,
                        reps="12-15",
                        rest_sec=60,
                        notes="Rear delt focus, squeeze at top"
                    ),
                ],
            ),
            WorkoutBlock(
                name="Superset 3 - Tricep/Bicep",
                notes="Arm antagonist pairing, 60s after pair",
                exercises=[
                    Exercise(
                        name=tricep,
                        sets=2,
                        reps="8-10",
                        rest_sec=0,
                        superset_with=bicep,
                        notes="Full ROM"
                    ),
                    Exercise(
                        name=bicep,
                        sets=2,
                        reps="10-12",
                        rest_sec=60,
                        notes="Control negative"
                    ),
                ],
            ),
        ],
    )


def build_lower_a(week: int = None) -> WorkoutTemplate:
    """
    Lower A: Quad & glute emphasis.

    Primary: Bilateral squat pattern
    Secondary: Hip thrust (glute max)
    Superset: Unilateral leg + calves
    """
    if week is None:
        week = get_week_number()

    return WorkoutTemplate(
        name="Lower A",
        focus="Quad & glute emphasis",
        estimated_time_min=44,
        warmup_notes="Hip circles, bodyweight squats, glute bridges",
        blocks=[
            WorkoutBlock(
                name="Main Lift - Squat Pattern",
                exercises=[
                    Exercise(
                        name="Dumbbell Squat",
                        sets=3,
                        reps="6-8",
                        rest_sec=90,
                        notes="Below parallel, drive through heels"
                    ),
                ],
            ),
            WorkoutBlock(
                name="Main Lift - Hip Dominant",
                exercises=[
                    Exercise(
                        name="Barbell Hip Thrust",  # Belt-loaded DB
                        sets=3,
                        reps="8-10",
                        rest_sec=90,
                        notes="Pause at top, full hip extension"
                    ),
                ],
            ),
            WorkoutBlock(
                name="Superset 1",
                notes="Alternating legs provides rest",
                exercises=[
                    Exercise(
                        name="Bulgarian Split Squat",
                        sets=2,
                        reps="8-10/leg",
                        rest_sec=0,
                        superset_with="Dumbbell Calf Raise",
                        notes="Rear foot elevated, stay upright"
                    ),
                    Exercise(
                        name="Dumbbell Calf Raise",
                        sets=2,
                        reps="15-20",
                        rest_sec=60,
                        notes="Full ROM, pause at top"
                    ),
                ],
            ),
        ],
    )


def build_lower_b(week: int = None) -> WorkoutTemplate:
    """
    Lower B: Posterior chain emphasis.

    Primary: Hip hinge (rotates between single-leg and bilateral)
    Superset: Split squat + calves
    Finisher: Secondary hinge pattern
    """
    if week is None:
        week = get_week_number()

    # Rotate hip hinge: Single-leg DL → Stiff-leg DL
    # When single-leg is primary, bilateral RDL is secondary (and vice versa)
    is_single_leg_week = week % 2 == 0

    if is_single_leg_week:
        primary_hinge = "Kettlebell Single-Leg Deadlift"
        primary_reps = "8-10/leg"
        primary_rest = 60
        secondary_hinge = "Dumbbell Stiff-Leg Deadlift"
    else:
        primary_hinge = "Dumbbell Stiff-Leg Deadlift"
        primary_reps = "10-12"
        primary_rest = 90
        secondary_hinge = "Kettlebell Single-Leg Deadlift"

    return WorkoutTemplate(
        name="Lower B",
        focus="Posterior chain emphasis",
        estimated_time_min=42,
        warmup_notes="Hip hinges, leg swings, glute activation",
        blocks=[
            WorkoutBlock(
                name="Main Lift - Hip Hinge",
                exercises=[
                    Exercise(
                        name=primary_hinge,
                        sets=3,
                        reps=primary_reps,
                        rest_sec=primary_rest,
                        notes="Hip hinge pattern, feel hamstring stretch"
                    ),
                ],
            ),
            WorkoutBlock(
                name="Superset 1",
                notes="Split squat + calves, 60s after pair",
                exercises=[
                    Exercise(
                        name="Bulgarian Split Squat",
                        sets=3,
                        reps="8-10/leg",
                        rest_sec=0,
                        superset_with="Dumbbell Calf Raise",
                        notes="Quad emphasis, control descent"
                    ),
                    Exercise(
                        name="Dumbbell Calf Raise",
                        sets=3,
                        reps="15-20",
                        rest_sec=60,
                        notes="Full ROM, pause at top"
                    ),
                ],
            ),
            WorkoutBlock(
                name="Finisher - Secondary Hinge",
                exercises=[
                    Exercise(
                        name=secondary_hinge,
                        sets=2,
                        reps="8-10/leg" if "Single-Leg" in secondary_hinge else "10-12",
                        rest_sec=45,
                        notes="Lighter weight, focus on stretch"
                    ),
                ],
            ),
        ],
    )


def build_core_circuit(week: int = None) -> WorkoutTemplate:
    """
    Core Circuit: Anti-movement focus for stability.

    Rotation through anti-extension, anti-lateral flexion, and flexion patterns.
    """
    if week is None:
        week = get_week_number()

    # Rotate anti-extension: Plank → Hollow Hold → Ab Rollout
    anti_ext = CORE_ANTI_EXTENSION.get_rotation(week)[0]

    # Rotate anti-lateral: Side Bend → Side Bridge
    anti_lat = CORE_ANTI_LATERAL.get_rotation(week)[0]

    # Rotate flexion: Hanging Leg Raise → Decline Crunch
    flexion = CORE_FLEXION.get_rotation(week)[0]

    return WorkoutTemplate(
        name="Core Circuit",
        focus="Anti-rotation & stability",
        estimated_time_min=8,
        warmup_notes="None needed if done post-lifting",
        blocks=[
            WorkoutBlock(
                name="Circuit (2 rounds)",
                notes="30s rest between rounds",
                exercises=[
                    Exercise(
                        name=anti_lat,
                        sets=2,
                        reps="12-15/side" if "Bend" in anti_lat else "30s/side",
                        rest_sec=0,
                        notes="Controlled movement"
                    ),
                    Exercise(
                        name=anti_ext,
                        sets=2,
                        reps="30-45s" if "Plank" in anti_ext or "Hold" in anti_ext else "8-10",
                        rest_sec=0,
                        notes="Brace core, neutral spine"
                    ),
                    Exercise(
                        name=flexion,
                        sets=2,
                        reps="10-15" if "Raise" not in flexion else "8-12",
                        rest_sec=30,
                        notes="Control the movement"
                    ),
                ],
            ),
        ],
    )


# =============================================================================
# WEEKLY SCHEDULE
# =============================================================================

def get_weekly_schedule(mode: str = "OPTIMAL") -> list[DayPlan]:
    """
    Get weekly schedule based on training mode.

    Modes:
        OPTIMAL: 4 resistance sessions, full cardio program
        MAINTENANCE: 3 resistance sessions, reduced volume
        DELOAD: 2 light sessions, focus on recovery
    """
    if mode == "OPTIMAL":
        return [
            DayPlan(
                day="Monday",
                primary="Upper A",
                secondary="Core Circuit",
                cardio="",
                mobility="5min upper body stretches",
                total_time_min=55,
            ),
            DayPlan(
                day="Tuesday",
                primary="Lower A",
                secondary="",
                cardio="Zone 2 Bike - 30min",
                mobility="5min hip stretches",
                total_time_min=80,
                notes="Cardio after lifting or PM session",
            ),
            DayPlan(
                day="Wednesday",
                primary="",
                secondary="",
                cardio="Intervals - Rowing (see protocol)",
                mobility="10min full body mobility",
                total_time_min=45,
                notes="Active recovery day - cardio only",
            ),
            DayPlan(
                day="Thursday",
                primary="Upper B",
                secondary="Core Circuit",
                cardio="",
                mobility="5min upper body stretches",
                total_time_min=55,
            ),
            DayPlan(
                day="Friday",
                primary="Lower B",
                secondary="",
                cardio="Zone 2 Row - 30min",
                mobility="5min hip stretches",
                total_time_min=80,
            ),
            DayPlan(
                day="Saturday",
                primary="",
                secondary="",
                cardio="Zone 2 choice - 45-60min",
                mobility="15min stretching/yoga",
                total_time_min=75,
                notes="Long easy cardio day",
            ),
            DayPlan(
                day="Sunday",
                primary="",
                secondary="",
                cardio="",
                mobility="15min recovery mobility",
                total_time_min=15,
                notes="Full rest - review next week's plan",
            ),
        ]

    elif mode == "MAINTENANCE":
        return [
            DayPlan(
                day="Monday",
                primary="Upper A",
                secondary="Core Circuit",
                cardio="",
                mobility="5min stretches",
                total_time_min=50,
                notes="Reduce to 2 sets per exercise",
            ),
            DayPlan(
                day="Tuesday",
                primary="",
                secondary="",
                cardio="Zone 2 Bike - 25min",
                mobility="10min mobility",
                total_time_min=35,
            ),
            DayPlan(
                day="Wednesday",
                primary="Lower A",
                secondary="",
                cardio="",
                mobility="5min hip stretches",
                total_time_min=45,
                notes="Reduce to 2 sets per exercise",
            ),
            DayPlan(
                day="Thursday",
                primary="",
                secondary="",
                cardio="Light intervals or Zone 2",
                mobility="10min full body",
                total_time_min=40,
            ),
            DayPlan(
                day="Friday",
                primary="Upper B + Lower B",
                secondary="",
                cardio="",
                mobility="5min stretches",
                total_time_min=50,
                notes="Combined: key compounds from each",
            ),
            DayPlan(
                day="Saturday",
                primary="",
                secondary="",
                cardio="Zone 2 choice - 30-45min",
                mobility="15min recovery",
                total_time_min=60,
            ),
            DayPlan(
                day="Sunday",
                primary="",
                secondary="",
                cardio="",
                mobility="10min mobility",
                total_time_min=10,
                notes="Rest - focus on sleep",
            ),
        ]

    else:  # DELOAD
        return [
            DayPlan(
                day="Monday",
                primary="",
                secondary="",
                cardio="Light Zone 2 - 20min",
                mobility="15min full body",
                total_time_min=35,
            ),
            DayPlan(
                day="Tuesday",
                primary="Light Full Body",
                secondary="",
                cardio="",
                mobility="10min stretches",
                total_time_min=35,
                notes="50% volume, -10% weight, no failure",
            ),
            DayPlan(
                day="Wednesday",
                primary="",
                secondary="",
                cardio="",
                mobility="15min yoga/stretching",
                total_time_min=15,
                notes="Full rest",
            ),
            DayPlan(
                day="Thursday",
                primary="",
                secondary="",
                cardio="Light Zone 2 - 20min",
                mobility="10min mobility",
                total_time_min=30,
            ),
            DayPlan(
                day="Friday",
                primary="Light Full Body",
                secondary="",
                cardio="",
                mobility="10min stretches",
                total_time_min=35,
                notes="Focus on movement quality, not load",
            ),
            DayPlan(
                day="Saturday",
                primary="",
                secondary="",
                cardio="",
                mobility="20min recovery mobility",
                total_time_min=20,
                notes="Active recovery only",
            ),
            DayPlan(
                day="Sunday",
                primary="",
                secondary="",
                cardio="",
                mobility="",
                total_time_min=0,
                notes="Full rest - prepare for next week",
            ),
        ]


# =============================================================================
# TEMPLATE ACCESS FUNCTIONS
# =============================================================================

def get_all_templates(week: int = None) -> dict[str, WorkoutTemplate]:
    """Get all workout templates for the given week."""
    if week is None:
        week = get_week_number()

    return {
        "Upper A": build_upper_a(week),
        "Upper B": build_upper_b(week),
        "Lower A": build_lower_a(week),
        "Lower B": build_lower_b(week),
        "Core Circuit": build_core_circuit(week),
    }


def get_template(name: str, week: int = None) -> Optional[WorkoutTemplate]:
    """Get a specific workout template by name."""
    templates = get_all_templates(week)
    return templates.get(name)


# For backward compatibility
ALL_TEMPLATES = get_all_templates()
UPPER_A = ALL_TEMPLATES["Upper A"]
UPPER_B = ALL_TEMPLATES["Upper B"]
LOWER_A = ALL_TEMPLATES["Lower A"]
LOWER_B = ALL_TEMPLATES["Lower B"]
CORE_CIRCUIT = ALL_TEMPLATES["Core Circuit"]


def adjust_template_for_mode(
    template: WorkoutTemplate,
    mode: str,
    weight_adjustments: dict[str, float] = None
) -> WorkoutTemplate:
    """
    Adjust a template for training mode.

    OPTIMAL: Full volume
    MAINTENANCE: Reduce to 2 sets where applicable
    DELOAD: Reduce sets and suggest lighter weights
    """
    import copy
    adjusted = copy.deepcopy(template)

    if mode == "OPTIMAL":
        return adjusted

    for block in adjusted.blocks:
        for exercise in block.exercises:
            if mode == "MAINTENANCE":
                # Reduce sets by 1 (min 2)
                exercise.sets = max(2, exercise.sets - 1)
            elif mode == "DELOAD":
                # Reduce to 2 sets, add deload note
                exercise.sets = 2
                if "DELOAD" not in exercise.notes:
                    exercise.notes = f"DELOAD: {exercise.notes}" if exercise.notes else "DELOAD week"

    # Adjust time estimate
    if mode == "MAINTENANCE":
        adjusted.estimated_time_min = int(template.estimated_time_min * 0.8)
    elif mode == "DELOAD":
        adjusted.estimated_time_min = int(template.estimated_time_min * 0.6)

    return adjusted


def format_workout_markdown(
    template: WorkoutTemplate,
    weight_targets: dict[str, float] = None
) -> str:
    """
    Format a workout template as markdown for the weekly report.

    Args:
        template: The workout template
        weight_targets: Dict of exercise name -> target weight from progression data
    """
    lines = []

    lines.append(f"### {template.name}: {template.focus}")
    lines.append(f"*~{template.estimated_time_min} min | Warmup: {template.warmup_notes}*")
    lines.append("")

    for block in template.blocks:
        lines.append(f"**{block.name}**")
        if block.notes:
            lines.append(f"*{block.notes}*")
        lines.append("")
        lines.append("| Exercise | Sets x Reps | Rest | Weight | Notes |")
        lines.append("|----------|-------------|------|--------|-------|")

        i = 0
        while i < len(block.exercises):
            ex = block.exercises[i]

            # Check if this is a superset
            if ex.superset_with and i + 1 < len(block.exercises):
                next_ex = block.exercises[i + 1]

                # Get weights
                weight1 = weight_targets.get(ex.name, "") if weight_targets else ""
                weight2 = weight_targets.get(next_ex.name, "") if weight_targets else ""
                w1_str = f"{weight1:.0f} lbs" if weight1 else "-"
                w2_str = f"{weight2:.0f} lbs" if weight2 else "-"

                # Format as superset
                lines.append(
                    f"| **A1.** {ex.name} | {ex.sets}x{ex.reps} | - | {w1_str} | {ex.notes} |"
                )
                lines.append(
                    f"| **A2.** {next_ex.name} | {next_ex.sets}x{next_ex.reps} | {next_ex.rest_sec}s | {w2_str} | {next_ex.notes} |"
                )
                i += 2
            else:
                # Single exercise
                weight = weight_targets.get(ex.name, "") if weight_targets else ""
                w_str = f"{weight:.0f} lbs" if weight else "-"

                lines.append(
                    f"| {ex.name} | {ex.sets}x{ex.reps} | {ex.rest_sec}s | {w_str} | {ex.notes} |"
                )
                i += 1

        lines.append("")

    return "\n".join(lines)


def format_weekly_schedule_markdown(schedule: list[DayPlan]) -> str:
    """Format weekly schedule as markdown."""
    lines = []

    lines.append("## Weekly Schedule")
    lines.append("")
    lines.append("| Day | Resistance | Cardio | Mobility | Time | Notes |")
    lines.append("|-----|------------|--------|----------|------|-------|")

    for day in schedule:
        primary = day.primary or "-"
        if day.secondary:
            primary = f"{day.primary} + {day.secondary}" if day.primary else day.secondary
        cardio = day.cardio or "-"
        mobility = day.mobility or "-"
        time = f"{day.total_time_min}min" if day.total_time_min else "-"
        notes = day.notes or ""

        lines.append(f"| {day.day} | {primary} | {cardio} | {mobility} | {time} | {notes} |")

    lines.append("")
    return "\n".join(lines)
