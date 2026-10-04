package ai.veritas.timeline;

import java.time.Instant;
import java.util.UUID;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/** One line of the investigation timeline: what the system did, and when. */
@Entity
@Table(name = "investigation_events")
public class InvestigationEvent {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "investigation_id", nullable = false)
    private UUID investigationId;

    @Column(nullable = false)
    private String type;

    @Column(nullable = false)
    private String message;

    private String detail;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    protected InvestigationEvent() {
    }

    public InvestigationEvent(UUID investigationId, String type, String message, String detail) {
        this.investigationId = investigationId;
        this.type = type;
        this.message = message.length() > 500 ? message.substring(0, 497) + "…" : message;
        this.detail = detail != null && detail.length() > 2000 ? detail.substring(0, 1997) + "…" : detail;
        this.createdAt = Instant.now();
    }

    public Long getId() {
        return id;
    }

    public UUID getInvestigationId() {
        return investigationId;
    }

    public String getType() {
        return type;
    }

    public String getMessage() {
        return message;
    }

    public String getDetail() {
        return detail;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }
}
