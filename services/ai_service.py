# ===============================================
# CIVICPULSE AI - AI Complaint Analysis Service
# ===============================================

import json
import re
import urllib.request
import urllib.error


class AIService:
    """AI analysis service with a deterministic local fallback.

    If AI_PROVIDER=openai and OPENAI_API_KEY is configured, the service can
    use the configured OpenAI-compatible endpoint. Otherwise, all analysis
    runs locally so complaint submission never depends on an external API.
    """

    CATEGORIES = {
        'road': 'Road Infrastructure',
        'water': 'Water Supply',
        'electricity': 'Electricity',
        'healthcare': 'Healthcare',
        'sanitation': 'Sanitation',
        'education': 'Education',
        'transport': 'Public Transport',
        'waste': 'Waste Management',
        'drainage': 'Drainage System',
        'other': 'Other'
    }

    CATEGORY_KEYWORDS = {
        'road': ['road', 'highway', 'pothole', 'pavement', 'connectivity', 'street', 'lane'],
        'water': ['water', 'supply', 'pipeline', 'contaminated', 'shortage', 'tap'],
        'electricity': ['power', 'electricity', 'blackout', 'transformer', 'outage', 'current'],
        'healthcare': ['hospital', 'clinic', 'medical', 'ambulance', 'doctor', 'health'],
        'sanitation': ['drain', 'sewage', 'sewer', 'hygiene', 'toilet'],
        'education': ['school', 'college', 'education', 'classroom', 'teacher', 'student'],
        'transport': ['bus', 'auto', 'traffic', 'transport', 'vehicle', 'parking'],
        'waste': ['waste', 'garbage', 'dustbin', 'landfill', 'trash', 'collection'],
        'drainage': ['drainage', 'flood', 'stagnant', 'waterlogging', 'stormwater'],
    }

    MULTILINGUAL_KEYWORDS = {
        'ta': {
            'road': ['சாலை', 'குழி', 'தெரு'], 'water': ['தண்ணீர்', 'குடிநீர்', 'நீர்'],
            'electricity': ['மின்சாரம்', 'மின்தடை'], 'healthcare': ['மருத்துவமனை', 'மருத்துவம்'],
            'education': ['பள்ளி', 'கல்வி'], 'transport': ['பேருந்து', 'போக்குவரத்து'],
            'waste': ['குப்பை', 'கழிவு'], 'drainage': ['வடிகால்', 'வெள்ளம்'],
            'sanitation': ['சுகாதாரம்', 'கழிவுநீர்']
        },
        'hi': {
            'road': ['सड़क', 'गड्ढा', 'मार्ग'], 'water': ['पानी', 'जल', 'पाइप'],
            'electricity': ['बिजली', 'विद्युत'], 'healthcare': ['अस्पताल', 'स्वास्थ्य'],
            'education': ['स्कूल', 'शिक्षा'], 'transport': ['बस', 'परिवहन'],
            'waste': ['कचरा', 'अपशिष्ट'], 'drainage': ['नाली', 'बाढ़'],
            'sanitation': ['स्वच्छता', 'सीवेज']
        },
        'te': {
            'road': ['రోడ్డు', 'గుంత', 'వీధి'], 'water': ['నీరు', 'తాగునీరు'],
            'electricity': ['విద్యుత్', 'కరెంట్'], 'healthcare': ['ఆసుపత్రి', 'ఆరోగ్యం'],
            'education': ['పాఠశాల', 'విద్య'], 'transport': ['బస్సు', 'రవాణా'],
            'waste': ['చెత్త', 'వ్యర్థాలు'], 'drainage': ['కాలువ', 'వరద']
        },
        'ka': {
            'road': ['ರಸ್ತೆ', 'ಗುಂಡಿ'], 'water': ['ನೀರು', 'ಕುಡಿಯುವ ನೀರು'],
            'electricity': ['ವಿದ್ಯುತ್'], 'healthcare': ['ಆಸ್ಪತ್ರೆ', 'ಆರೋಗ್ಯ'],
            'education': ['ಶಾಲೆ', 'ಶಿಕ್ಷಣ'], 'transport': ['ಬಸ್', 'ಸಾರಿಗೆ'],
            'waste': ['ಕಸ', 'ತ್ಯಾಜ್ಯ'], 'drainage': ['ಚರಂಡಿ', 'ಪ್ರವಾಹ']
        },
        'ml': {
            'road': ['റോഡ്', 'കുഴി', 'തെരുവ്'], 'water': ['വെള്ളം', 'കുടിവെള്ളം'],
            'electricity': ['വൈദ്യുതി'], 'healthcare': ['ആശുപത്രി', 'ആരോഗ്യം'],
            'education': ['സ്കൂൾ', 'വിദ്യാഭ്യാസം'], 'transport': ['ബസ്', 'ഗതാഗതം'],
            'waste': ['മാലിന്യം', 'മാലിന്യസംസ്‌കരണം'], 'drainage': ['ഓട', 'വെള്ളപ്പൊക്കം']
        }
    }

    ISSUE_TYPES = {
        'road': 'Road/Pothole Issue',
        'water': 'Water Supply Issue',
        'electricity': 'Power/Outage Issue',
        'healthcare': 'Healthcare Access Issue',
        'sanitation': 'Sanitation Issue',
        'education': 'Education Facility Issue',
        'transport': 'Public Transport Issue',
        'waste': 'Garbage Collection',
        'drainage': 'Drainage/Flooding Issue',
        'other': 'General Civic Issue'
    }

    DEPARTMENTS = {
        'road': 'Roads & Highways',
        'water': 'Water Supply',
        'electricity': 'Electricity Board',
        'healthcare': 'Health Department',
        'sanitation': 'Sanitation',
        'education': 'Education Department',
        'transport': 'Transport Department',
        'waste': 'Sanitation',
        'drainage': 'Public Works / Drainage',
        'other': 'General Administration'
    }

    LANGUAGES = {
        'en': 'English',
        'hi': 'Hindi',
        'ta': 'Tamil',
        'te': 'Telugu',
        'ka': 'Kannada',
        'ml': 'Malayalam'
    }

    @staticmethod
    def detect_language(text):
        """Lightweight language detection for common Indian scripts."""
        text = text or ''
        if re.search(r'[\u0B80-\u0BFF]', text):
            return 'ta'
        if re.search(r'[\u0900-\u097F]', text):
            return 'hi'
        if re.search(r'[\u0C00-\u0C7F]', text):
            return 'te'
        if re.search(r'[\u0C80-\u0CFF]', text):
            return 'ka'
        if re.search(r'[\u0D00-\u0D7F]', text):
            return 'ml'
        return 'en'

    @classmethod
    def classify_category(cls, text):
        text_lower = (text or '').lower()
        scores = {
            category: sum(1 for kw in keywords if kw in text_lower)
            for category, keywords in cls.CATEGORY_KEYWORDS.items()
        }
        best = max(scores, key=scores.get) if scores else 'other'
        return best if scores.get(best, 0) else 'other'

    @staticmethod
    def analyze_urgency(text, category=None):
        text_lower = (text or '').lower()
        urgent_keywords = [
            'emergency', 'critical', 'urgent', 'immediate', 'dying',
            'severe', 'danger', 'unsafe', 'accident', 'fire', 'flood'
        ]
        moderate_keywords = [
            'issue', 'problem', 'needed', 'necessary', 'poor', 'bad',
            'not working', 'days', 'week', 'shortage'
        ]

        if any(kw in text_lower for kw in urgent_keywords):
            return 'High'
        if re.search(r'\b([3-9]|[1-9][0-9]+)\s+(day|days|week|weeks)\b', text_lower):
            return 'High'
        if re.search(r'\b(three|four|five|six|seven|eight|nine|ten|several)\s+(day|days|week|weeks)\b', text_lower):
            return 'High'
        if any(kw in text_lower for kw in moderate_keywords):
            return 'Moderate'
        return 'Low'

    @staticmethod
    def classify_priority(urgency, text):
        text_lower = (text or '').lower()
        critical_terms = [
            'life threatening', 'life-threatening', 'dangerous', 'fire',
            'accident', 'collapse', 'electrocution', 'contamination',
            'major water leakage', 'burst water pipe', 'severe flooding',
            'road obstruction', 'public safety', 'exposed live wire', 'electrical hazard'
        ]
        if any(term in text_lower for term in critical_terms):
            return 'Critical'
        if urgency == 'High':
            return 'High'
        if urgency == 'Moderate':
            return 'Medium'
        return 'Low'

    @classmethod
    def classify_sentiment(cls, text):
        text_lower = (text or '').lower()
        negative = [
            'angry', 'frustrated', 'terrible', 'worst', 'unsafe', 'bad',
            'problem', 'issue', 'failed', 'dirty', 'danger', 'not working',
            'broken', 'delay', 'delayed', 'complaint', 'not collected',
            'not available', 'shortage'
        ]
        positive = ['thank', 'thanks', 'good', 'appreciate', 'resolved', 'happy']
        neg_score = sum(1 for word in negative if word in text_lower)
        pos_score = sum(1 for word in positive if word in text_lower)
        if neg_score > pos_score:
            return 'Negative'
        if pos_score > neg_score:
            return 'Positive'
        return 'Neutral'

    @classmethod
    def local_smart_analysis(cls, request_data):
        text = ' '.join(
            str(request_data.get(key, '') or '')
            for key in ('title', 'description')
        ).strip()

        selected_category = str(request_data.get('category', '') or '').strip().lower()
        # Combine the citizen's selected category with text evidence. The
        # selected value receives a small contextual boost, but strong text
        # evidence can still override it.
        scores = {
            category: sum(1 for kw in keywords if kw in text.lower())
            for category, keywords in cls.CATEGORY_KEYWORDS.items()
        }
        detected_lang = request_data.get('original_language') or request_data.get('language') or cls.detect_language(text)
        for category, keywords in cls.MULTILINGUAL_KEYWORDS.get(detected_lang, {}).items():
            scores[category] = scores.get(category, 0) + sum(
                1 for kw in keywords if kw in text
            )
        if selected_category in cls.CATEGORIES and selected_category != 'other':
            scores[selected_category] = scores.get(selected_category, 0) + 2
        category_key = max(scores, key=scores.get) if scores else 'other'
        if scores.get(category_key, 0) == 0:
            category_key = 'other'
        urgency = cls.analyze_urgency(text, category_key)
        priority = cls.classify_priority(urgency, text)
        sentiment = cls.classify_sentiment(text)

        keyword_hits = sum(
            1 for kw in cls.CATEGORY_KEYWORDS.get(category_key, [])
            if kw in text.lower()
        )
        confidence = min(0.98, 0.55 + (keyword_hits * 0.08))
        if category_key == 'other':
            confidence = 0.45
        urgency_confidence = min(0.95, confidence if urgency != 'Low' else max(0.55, confidence - 0.05))
        priority_confidence = min(0.95, urgency_confidence + (0.05 if priority in ('High', 'Critical') else 0))
        recommendation_confidence = min(0.95, (confidence + urgency_confidence) / 2)

        department = cls.DEPARTMENTS.get(category_key, cls.DEPARTMENTS['other'])
        issue_type = cls.ISSUE_TYPES.get(category_key, cls.ISSUE_TYPES['other'])

        return {
            'category_classified': cls.CATEGORIES.get(category_key, 'Other'),
            'category_key': category_key,
            'issue_type': issue_type,
            'priority': priority,
            'urgency_level': urgency,
            'recommended_department': department,
            'sentiment': sentiment,
            'confidence_score': round(confidence, 2),
            'urgency_confidence': round(urgency_confidence, 2),
            'priority_confidence': round(priority_confidence, 2),
            'recommendation_confidence': round(recommendation_confidence, 2),
            'ai_provider': 'local'
        }

    @classmethod
    def _openai_analysis(cls, request_data):
        """Call an OpenAI-compatible JSON endpoint without exposing the key."""
        from config import Config

        if not Config.OPENAI_API_KEY:
            raise RuntimeError('OPENAI_API_KEY is not configured.')

        prompt = {
            'title': request_data.get('title', ''),
            'description': request_data.get('description', ''),
            'category_selected': request_data.get('category', ''),
            'location': {
                'state': request_data.get('state', ''),
                'district': request_data.get('district', ''),
                'local_area': request_data.get('local_area', '')
            }
        }

        system = (
            "You analyze civic complaints. Return JSON only with keys: "
            "category_classified, issue_type, priority, urgency_level, "
            "recommended_department, sentiment, confidence_score. "
            "priority must be Critical, High, Medium, or Low; urgency must "
            "be High, Moderate, or Low; confidence_score must be 0 to 1."
        )
        payload = json.dumps({
            'model': Config.OPENAI_MODEL,
            'temperature': 0,
            'response_format': {'type': 'json_object'},
            'messages': [
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': json.dumps(prompt)}
            ]
        }).encode('utf-8')

        url = Config.OPENAI_BASE_URL.rstrip('/') + '/chat/completions'
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {Config.OPENAI_API_KEY}'
            },
            method='POST'
        )

        with urllib.request.urlopen(req, timeout=12) as response:
            body = json.loads(response.read().decode('utf-8'))

        content = body['choices'][0]['message']['content']
        result = json.loads(content)

        required = [
            'category_classified', 'issue_type', 'priority',
            'urgency_level', 'recommended_department', 'sentiment',
            'confidence_score'
        ]
        if any(key not in result for key in required):
            raise ValueError('AI provider returned incomplete analysis.')

        result['confidence_score'] = max(
            0.0, min(1.0, float(result['confidence_score']))
        )
        result['urgency_confidence'] = result['confidence_score']
        result['priority_confidence'] = result['confidence_score']
        result['recommendation_confidence'] = result['confidence_score']
        result['ai_provider'] = 'openai'
        return result


    @classmethod
    def public_assistant_answer(cls, question, language='en'):
        """Answer a public website-help question without accessing private data."""
        from config import Config
        if Config.AI_PROVIDER != 'openai' or not Config.OPENAI_API_KEY:
            return None
        prompt = (
            "You are CivicPulse AI's public website assistant. Answer only questions "
            "about submitting complaints, tracking complaints, civic service categories, "
            "department information, FAQs and navigation. Never access or invent private "
            "complaint records. Never ask for passwords, tokens or API keys. Never claim "
            "that an action was completed. Keep the answer under 100 words. "
            f"Respond in {'Tamil' if language == 'ta' else 'English'}.\n\nQuestion: {question}"
        )
        payload = json.dumps({
            'model': Config.OPENAI_MODEL,
            'temperature': 0.2,
            'messages': [
                {'role': 'system', 'content': prompt},
                {'role': 'user', 'content': question}
            ]
        }).encode('utf-8')
        url = Config.OPENAI_BASE_URL.rstrip('/') + '/chat/completions'
        req = urllib.request.Request(
            url, data=payload,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {Config.OPENAI_API_KEY}'
            },
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=8) as response:
            body = json.loads(response.read().decode('utf-8'))
        answer = str(body['choices'][0]['message']['content']).strip()
        return answer[:1200] if answer else None

    @classmethod
    def perform_smart_analysis(cls, request_data):
        """Perform smart analysis, falling back to local analysis on failure."""
        from config import Config

        if Config.AI_PROVIDER == 'openai' and Config.OPENAI_API_KEY:
            try:
                return cls._openai_analysis(request_data)
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
                    ValueError, KeyError, json.JSONDecodeError, RuntimeError):
                # Submission must continue even when the remote AI service fails.
                pass

        return cls.local_smart_analysis(request_data)

    # ------------------------------------------------------------------
    # Existing analysis API retained for backward compatibility.
    # ------------------------------------------------------------------

    @staticmethod
    def calculate_infrastructure_gap(category, district, population):
        # Keep the existing conceptual field, but make it deterministic.
        base = {
            'road': 6.0, 'water': 6.5, 'electricity': 5.5,
            'healthcare': 7.0, 'sanitation': 7.0, 'education': 5.5,
            'transport': 5.5, 'waste': 7.0, 'drainage': 6.5, 'other': 5.0
        }
        return min(10.0, base.get(category, 5.0))

    @staticmethod
    def find_similar_requests(category, location):
        # The caller now prefers real database counts. This compatibility
        # fallback is retained only for older code paths.
        return 0

    @staticmethod
    def generate_recommendation(category, urgency, infra_gap, similar_count):
        recommendations = {
            'road': "Review road condition and prioritize safety-related repairs.",
            'water': "Inspect water supply infrastructure and address service interruptions.",
            'electricity': "Assess the local distribution network and resolve reported outages.",
            'healthcare': "Review healthcare access and route the issue to the health department.",
            'sanitation': "Review sanitation facilities and service coverage in the affected area.",
            'education': "Assess the reported education facility or service requirement.",
            'transport': "Review public transport service and route-related constraints.",
            'waste': "Review waste collection coverage and missed-collection reports.",
            'drainage': "Inspect drainage capacity and address flooding or waterlogging risks.",
            'other': "Route the complaint for departmental review and further assessment."
        }
        return recommendations.get(category, recommendations['other'])

    @staticmethod
    def generate_explainability_factors(urgency, infra_gap, similar_count, population):
        return {
            'urgency': f"Urgency classified as {urgency}.",
            'infrastructure_gap': f"Existing gap indicator: {infra_gap:.1f}/10.",
            'similar_requests': f"{similar_count} matching requests found in available data.",
            'population_impact': f"Population impact estimate: {population:,}."
        }

    @classmethod
    def perform_full_analysis(cls, request_data):
        smart = cls.perform_smart_analysis(request_data)
        category_key = smart.get('category_key') or cls.classify_category(
            request_data.get('description', '')
        )

        # Existing dashboard fields remain populated without random data.
        infra_gap = cls.calculate_infrastructure_gap(
            category_key, request_data.get('district', ''), 0
        )
        recommendation = cls.generate_recommendation(
            category_key,
            smart['urgency_level'],
            infra_gap,
            0
        )

        return {
            'language_detected': cls.detect_language(request_data.get('description', '')),
            'category_classified': category_key,
            'urgency_level': smart['urgency_level'],
            'infrastructure_gap': round(infra_gap, 1),
            'similar_requests_count': 0,
            'population_impacted': 0,
            'ai_recommendation': recommendation,
            'explainability_factors': cls.generate_explainability_factors(
                smart['urgency_level'], infra_gap, 0, 0
            ),
            'human_review_required': True,
            'issue_type': smart['issue_type'],
            'priority': smart['priority'],
            'recommended_department': smart['recommended_department'],
            'sentiment': smart['sentiment'],
            'confidence_score': smart['confidence_score'],
            'ai_provider': smart['ai_provider']
        }
