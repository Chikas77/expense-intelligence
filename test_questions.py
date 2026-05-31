from categorization_questions import get_disambiguation_questions, process_answer
from parser import categorize_transaction_flow

# Test 1: Family member, regular support
transaction_mock = type('obj', (object,), {
    'description': 'Sent Ksh 5,000 to JANE',
    'amount': 5000,
    'category': 'transfer'
})()

# Get first question
q1 = get_disambiguation_questions(transaction_mock)
print("Q1:", q1['question'])
print("Options:", [opt['label'] for opt in q1['options']])

# Simulate user answer: "A" (person)
q2 = process_answer(1, 'A')
print("\nQ2:", q2['question'])

# Simulate user answer: "A1" (family)
q3 = process_answer('2A', 'A1')
print("\nQ3:", q3['question'])

# Simulate user answer: "A1-i" (regular support)
result = process_answer('3A', 'A1-i')
print("\nFinal Category:", result['category'])  # Should be "Family Support"
assert result['category'] == 'Family Support'

# Test 2: Friend, chama
q2b = process_answer(1, 'A')
q2b = process_answer('2A', 'A2')
print("\n\nQ2B:", q2b['question'])

result2 = process_answer('3B', 'A2-i')
print("Final Category:", result2['category'])  # Should be "Chama"
assert result2['category'] == 'Chama'

# Test 2b: Unsure branch should allow clarifying person vs service
q3c = process_answer(1, 'C')
print("\n\nQ3C:", q3c['question'])
assert q3c['question_level'] == '3'
q4 = process_answer('3', 'C1')
print("Next Question after C1:", q4['question'])
assert q4['question_level'] == 'C1'
q5 = process_answer('C1', 'B')
print("Final branch question after C1 -> B:", q5['question'])
assert q5['question_level'] == '2B'
result3 = process_answer('2B', 'B4')
print("Final Category via unsure branch:", result3['category'])
assert result3['category'] == 'Entertainment'

# Test 3: Full transaction flow wrapper
transaction_mock_2 = type('obj', (object,), {
    'description': 'Sent Ksh 2,500 to PETER',
    'amount': 2500,
    'category': 'transfer'
})()
flow_category, flow_sub_type, flow_needs_input, flow_question = categorize_transaction_flow(transaction_mock_2)
print("\nFlow Q1:", flow_question['question'])
print("Flow Options:", [opt['label'] for opt in flow_question['options']])
assert flow_question is not None
assert flow_needs_input is True
assert len(flow_question['options']) > 0

print("\nAll tests passed.")
