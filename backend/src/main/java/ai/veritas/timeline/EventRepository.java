package ai.veritas.timeline;

import java.util.List;
import java.util.UUID;

import org.springframework.data.jpa.repository.JpaRepository;

public interface EventRepository extends JpaRepository<InvestigationEvent, Long> {

    List<InvestigationEvent> findByInvestigationIdOrderByCreatedAtAscIdAsc(UUID investigationId);
}
