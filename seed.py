# CivicPulse AI - Non-destructive demo seed
#
# This script NEVER drops tables or deletes existing records.
# It only creates missing demo users, departments, locations, projects and
# demo requests when the corresponding records do not already exist.

from datetime import datetime
from app import app, db, init_db, _backfill_department_references
from models import User, CitizenRequest, RequestAnalysis, Location, Project, Department, SLAConfig
from services.ai_service import AIService


def seed_database():
    init_db()
    with app.app_context():
        departments = {}
        names = ['Sanitation', 'Water Supply', 'Road Maintenance', 'Drainage',
                 'Street Lighting', 'Electricity', 'Parks', 'Public Services']
        for name in names:
            obj = Department.query.filter_by(name=name).first()
            if not obj:
                obj = Department(name=name, is_active=True)
                db.session.add(obj)
                db.session.flush()
            departments[name] = obj

        users = {}
        for username, email, role in [
            ('demo_citizen', 'citizen@demo.civicpulse.ai', 'Citizen'),
            ('demo_officer', 'officer@demo.civicpulse.ai', 'Officer'),
            ('demo_admin', 'admin@demo.civicpulse.ai', 'Admin')
        ]:
            user = User.query.filter_by(username=username).first()
            if not user:
                user = User(username=username, email=email, role=role)
                user.set_password('demo123')
                db.session.add(user)
                db.session.flush()
            users[role] = user
        users['Officer'].department_id = departments['Public Services'].id

        locations_data = [
            ('Tamil Nadu', 'Salem'), ('Maharashtra', 'Nashik'),
            ('Karnataka', 'Davangere'), ('Telangana', 'Warangal'),
            ('Andhra Pradesh', 'Vizag')
        ]
        locations = {}
        for state, district in locations_data:
            loc = Location.query.filter_by(state=state, district=district).first()
            if not loc:
                loc = Location(state=state, district=district)
                db.session.add(loc)
                db.session.flush()
            locations[(state, district)] = loc

        # Keep existing data. Only create demo requests if none exist.
        if CitizenRequest.query.count() == 0:
            demo = [
                ('road', 'Main road has potholes and needs urgent repair.', 'Tamil Nadu', 'Salem', 'Central Ward'),
                ('water', 'Water supply is irregular and residents need a reliable pipeline.', 'Tamil Nadu', 'Salem', 'East Ward'),
                ('electricity', 'Frequent power outages are affecting public services.', 'Maharashtra', 'Nashik', 'Industrial Area'),
                ('healthcare', 'The nearest healthcare facility is far from the locality.', 'Maharashtra', 'Nashik', 'Rural Area'),
                ('education', 'School infrastructure needs maintenance and safety improvements.', 'Karnataka', 'Davangere', 'Village XYZ'),
                ('sanitation', 'Open drainage and missed waste collection are affecting the area.', 'Telangana', 'Warangal', 'Slum Area'),
                ('transport', 'Public transport is limited and buses are infrequent.', 'Andhra Pradesh', 'Vizag', 'Outer Region')
            ]
            for category, description, state, district, local_area in demo:
                cr = CitizenRequest(
                    user_id=users['Citizen'].id,
                    title=f'{category.title()} civic issue',
                    category=category,
                    description=description,
                    language='en',
                    original_language='en',
                    original_text=description,
                    normalized_text=description,
                    input_mode='text',
                    state=state, district=district, local_area=local_area,
                    status='Submitted'
                )
                cr.generate_request_id()
                db.session.add(cr)
                db.session.flush()
                result = AIService.perform_full_analysis({
                    'title': cr.title, 'description': description, 'category': category,
                    'state': state, 'district': district, 'local_area': local_area,
                    'language': 'en', 'original_language': 'en'
                })
                details = {
                    'category': result.get('confidence_score'),
                    'urgency': result.get('urgency_confidence', result.get('confidence_score')),
                    'priority': result.get('priority_confidence', result.get('confidence_score')),
                    'recommendation': result.get('recommendation_confidence', result.get('confidence_score')),
                    'methodology': 'Local deterministic keyword/context analysis'
                }
                db.session.add(RequestAnalysis(
                    request_id=cr.request_id,
                    language_detected='en',
                    category_classified=result['category_classified'],
                    urgency_level=result['urgency_level'],
                    infrastructure_gap=result['infrastructure_gap'],
                    similar_requests_count=0,
                    population_impacted=0,
                    ai_recommendation=result['ai_recommendation'],
                    explainability_factors=result['explainability_factors'],
                    issue_type=result.get('issue_type'),
                    priority=result.get('priority'),
                    original_priority=result.get('priority'),
                    recommended_department=result.get('recommended_department'),
                    recommended_department_id=next(
                        (d.id for d in departments.values()
                         if d.name.strip().lower() == str(result.get('recommended_department') or '').strip().lower()),
                        None
                    ),
                    sentiment=result.get('sentiment'),
                    confidence_score=result.get('confidence_score'),
                    confidence_details=details,
                    ai_provider=result.get('ai_provider', 'local'),
                    human_review_required=True,
                    review_status='Review Required'
                ))

        # Make the bundled demo officer useful immediately. This touches only
        # requests owned by the dedicated demo citizen and never reassigns a
        # real user's requests.
        demo_officer = users['Officer']
        demo_citizen = users['Citizen']
        demo_requests = CitizenRequest.query.filter_by(user_id=demo_citizen.id).order_by(CitizenRequest.id.asc()).all()
        demo_statuses = ['In-Progress', 'Pending', 'Pending', 'Analyzed', 'Resolved', 'Submitted', 'Resolved']
        for index, complaint in enumerate(demo_requests):
            if complaint.assigned_officer_id is None:
                complaint.assigned_officer_id = demo_officer.id
                complaint.assigned_at = complaint.assigned_at or datetime.utcnow()
            if complaint.status in (None, '', 'Analyzed') and index < len(demo_statuses):
                complaint.status = demo_statuses[index]
            if complaint.analysis and not complaint.analysis.priority:
                complaint.analysis.priority = {
                    'High': 'High', 'Moderate': 'Medium', 'Low': 'Low'
                }.get(complaint.analysis.urgency_level, 'Low')
                complaint.analysis.original_priority = complaint.analysis.priority

        # Keep location metrics based on actual stored records.
        for key, loc in locations.items():
            state, district = key
            requests = CitizenRequest.query.filter_by(state=state, district=district).all()
            loc.citizen_demand_count = len(requests)
            gaps = [r.analysis.infrastructure_gap for r in requests if r.analysis and r.analysis.infrastructure_gap is not None]
            loc.infrastructure_gap_score = round(sum(gaps) / len(gaps), 1) if gaps else 0.0
            if not loc.projects and requests:
                db.session.add(Project(
                    location_id=loc.id,
                    title=f'Demo project context - {district}',
                    category=requests[0].category,
                    status='Planned',
                    estimated_people_impacted=None
                ))

        db.session.commit()
        _backfill_department_references()
        print('CivicPulse AI demo seed completed without deleting existing data.')
        print('Demo credentials: demo_citizen/demo123, demo_officer/demo123, demo_admin/demo123')


if __name__ == '__main__':
    seed_database()
