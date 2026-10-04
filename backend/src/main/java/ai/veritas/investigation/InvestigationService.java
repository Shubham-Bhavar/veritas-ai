package ai.veritas.investigation;

import java.util.List;
import java.util.UUID;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import ai.veritas.ai.AiClient;
import ai.veritas.common.ApiException;
import ai.veritas.document.DocumentRepository;
import ai.veritas.document.EvidenceDocument;
import ai.veritas.document.FileStorage;
import ai.veritas.timeline.EventService;
import ai.veritas.user.UserRepository;

@Service
public class InvestigationService {

    private final InvestigationRepository investigations;
    private final DocumentRepository documents;
    private final EventService events;
    private final AiClient ai;
    private final FileStorage storage;
    private final UserRepository users;

    public InvestigationService(InvestigationRepository investigations, DocumentRepository documents, EventService events,
            AiClient ai, FileStorage storage, UserRepository users) {
        this.users = users;
        this.investigations = investigations;
        this.documents = documents;
        this.events = events;
        this.ai = ai;
        this.storage = storage;
    }

    /** Loads an investigation the user owns. Someone else's is reported as "not found", never "forbidden". */
    public Investigation owned(UUID id, Long userId) {
        return investigations.findByIdAndOwnerId(id, userId)
                .orElseThrow(() -> ApiException.notFound("Investigation not found."));
    }

    public List<Investigation> list(Long userId) {
        return investigations.findByOwnerIdOrderByUpdatedAtDesc(userId);
    }

    @Transactional
    public Investigation create(Long userId, String title, String description, boolean demo) {
        if (!users.existsById(userId)) {
            // a validly signed token whose account no longer exists
            throw ApiException.unauthorized("Your session has ended. Please sign in again.");
        }
        Investigation inv = investigations.save(new Investigation(userId, title.trim(),
                description == null || description.isBlank() ? null : description.trim(), demo));
        events.record(inv.getId(), "investigation.created", "Investigation opened: " + inv.getTitle());
        return inv;
    }

    @Transactional
    public Investigation rename(UUID id, Long userId, String title, String description) {
        Investigation inv = owned(id, userId);
        inv.setTitle(title.trim());
        inv.setDescription(description == null || description.isBlank() ? null : description.trim());
        inv.touch();
        return inv;
    }

    public void delete(UUID id, Long userId) {
        Investigation inv = owned(id, userId);
        investigations.delete(inv);
        ai.deleteCollection(inv.getId());
        storage.deleteInvestigation(inv.getId());
    }

    public List<EvidenceDocument> documents(UUID id) {
        return documents.findByInvestigationIdOrderByCreatedAtAsc(id);
    }

    @Transactional
    public void touch(UUID id) {
        investigations.findById(id).ifPresent(Investigation::touch);
    }
}
