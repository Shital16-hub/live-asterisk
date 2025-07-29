from typing import List, Dict, Any

class Agent:
    def get_best_options(self, question: str) -> List[Dict[str, Any]]:
        """Get best options for a given question."""
        try:
            # Enhanced options for different scenarios
            options = [
                {
                    "id": "greeting",
                    "text": "Hello! How can I help you today?",
                    "type": "greeting",
                    "confidence": 0.95
                },
                {
                    "id": "expert_available",
                    "text": "I notice an expert is available. Would you like me to connect you with them?",
                    "type": "expert_connection",
                    "confidence": 0.9
                },
                {
                    "id": "silence_detected",
                    "text": "I notice there's been a pause in the conversation. Is there anything specific you'd like to discuss?",
                    "type": "silence_break",
                    "confidence": 0.85
                },
                {
                    "id": "clarification",
                    "text": "Could you please provide more details about your question?",
                    "type": "clarification",
                    "confidence": 0.8
                },
                {
                    "id": "summarize",
                    "text": "Let me summarize what we've discussed so far...",
                    "type": "summary",
                    "confidence": 0.75
                },
                {
                    "id": "redirect",
                    "text": "This might be better handled by our expert team. Would you like me to connect you?",
                    "type": "expert_redirect",
                    "confidence": 0.7
                },
                {
                    "id": "follow_up",
                    "text": "Would you like to explore this topic further?",
                    "type": "follow_up",
                    "confidence": 0.65
                },
                {
                    "id": "resources",
                    "text": "I can provide some helpful resources on this topic. Would that be useful?",
                    "type": "resources",
                    "confidence": 0.6
                },
                {
                    "id": "schedule",
                    "text": "Would you like to schedule a follow-up session with an expert?",
                    "type": "scheduling",
                    "confidence": 0.55
                },
                {
                    "id": "feedback",
                    "text": "How has your experience been so far? Is there anything we can improve?",
                    "type": "feedback",
                    "confidence": 0.5
                }
            ]
            
            # Add context-specific options based on question content
            if "help" in question.lower():
                options.append({
                    "id": "help_resources",
                    "text": "I can guide you through our help resources. What specific area do you need assistance with?",
                    "type": "help",
                    "confidence": 0.85
                })
            
            if "problem" in question.lower() or "issue" in question.lower():
                options.append({
                    "id": "troubleshooting",
                    "text": "Let's troubleshoot this step by step. Can you describe the issue in more detail?",
                    "type": "troubleshooting",
                    "confidence": 0.8
                })
            
            if "price" in question.lower() or "cost" in question.lower():
                options.append({
                    "id": "pricing_info",
                    "text": "I can provide detailed pricing information. What specific service are you interested in?",
                    "type": "pricing",
                    "confidence": 0.75
                })
            
            # Sort options by confidence
            options.sort(key=lambda x: x["confidence"], reverse=True)
            
            # Return top 5 options
            return options[:5]
            
        except Exception as e:
            logger.error(f"Error getting best options: {str(e)}")
            return [] 