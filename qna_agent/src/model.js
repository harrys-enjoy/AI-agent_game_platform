export class MockModelAdapter {
  async generate({ system, question, evidence = [], maxOutputChars = 800 }) {
    const basis = evidence.length > 0 ? evidence.join(' ') : '현재 제공된 근거가 없습니다.';
    const answer = `${basis} 질문: ${question}`;
    return { answer: answer.slice(0, maxOutputChars), usage: null, system };
  }
}
