package ai.veritas.question;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

import org.springframework.data.jpa.repository.JpaRepository;

interface QuestionRepository extends JpaRepository<Entities.Question, UUID> {
    List<Entities.Question> findByInvestigationIdOrderByCreatedAtDesc(UUID investigationId);

    Optional<Entities.Question> findByIdAndInvestigationId(UUID id, UUID investigationId);
}

interface AnswerRepository extends JpaRepository<Entities.Answer, UUID> {
    Optional<Entities.Answer> findByQuestionId(UUID questionId);

    List<Entities.Answer> findByQuestionIdIn(List<UUID> questionIds);
}

interface ClaimRepository extends JpaRepository<Entities.ClaimRow, Long> {
}

interface CitationRepository extends JpaRepository<Entities.CitationRow, Long> {
}

interface ConflictRepository extends JpaRepository<Entities.ConflictRow, Long> {
}
