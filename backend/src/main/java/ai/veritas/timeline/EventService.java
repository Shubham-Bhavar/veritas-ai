package ai.veritas.timeline;

import java.util.List;
import java.util.UUID;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

@Service
public class EventService {

    private final EventRepository repo;

    public EventService(EventRepository repo) {
        this.repo = repo;
    }

    /** Recorded in its own transaction so the timeline survives a failure in the caller. */
    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void record(UUID investigationId, String type, String message, String detail) {
        repo.save(new InvestigationEvent(investigationId, type, message, detail));
    }

    public void record(UUID investigationId, String type, String message) {
        record(investigationId, type, message, null);
    }

    @Transactional(readOnly = true)
    public List<InvestigationEvent> timeline(UUID investigationId) {
        return repo.findByInvestigationIdOrderByCreatedAtAscIdAsc(investigationId);
    }
}
