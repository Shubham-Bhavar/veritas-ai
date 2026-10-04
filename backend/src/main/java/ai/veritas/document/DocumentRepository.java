package ai.veritas.document;

import java.util.Collection;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

import org.springframework.data.jpa.repository.JpaRepository;

public interface DocumentRepository extends JpaRepository<EvidenceDocument, UUID> {

    List<EvidenceDocument> findByInvestigationIdOrderByCreatedAtAsc(UUID investigationId);

    Optional<EvidenceDocument> findByIdAndInvestigationId(UUID id, UUID investigationId);

    Optional<EvidenceDocument> findByInvestigationIdAndSha256(UUID investigationId, String sha256);

    long countByInvestigationId(UUID investigationId);

    List<EvidenceDocument> findByStatusIn(Collection<EvidenceDocument.Status> statuses);
}
